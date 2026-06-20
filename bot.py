# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Osvaldo Cipriano (github.com/nunchuckcoder)
"""
Bot IRC com integração Telegram.

Correcções nesta versão (v4):
  • Rate limit refactorizado para timestamp-bucket: deixa de criar uma
    asyncio.Task por cada comando recebido (que ficava 60s em sleep).
    Em vez disso, mantém-se um tuplo (count, window_start) por chave
    e a janela é avaliada na próxima chamada. GC periódico do dict.
  • Audit log dividido por nível: INFO mostra apenas nick+comando+target
    (suficiente para visibilidade operacional, evita expor IP/vhost no
    ficheiro de log a quem o lê); DEBUG mostra hostmask completo + args
    para forensics quando necessário.
"""
import asyncio
import signal
import socket
import ssl
import sys
import time

import irc.client
import irc.connection

from logger import logger
from config import (
    SERVER,
    PORT,
    NICK,
    PASSWORD,
    CANAIS,
    CANAIS_COM_ALERTAS,
    BOAS_VINDAS,
    IRC_MONITORED_BOTS,
    IRC_PING_INTERVAL,
    IRC_PONG_TIMEOUT,
)
from plugins.seen import log_seen_async, init_db
from plugins.commands import executar_comando
from plugins.telegram import enviar_telegram, h
from plugins.telegram_control import TelegramController
from plugins.http_clients import close_all as close_http_sessions
from plugins.irc_validate import valid_nick, IRCValidationError

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


PING_INTERVAL = IRC_PING_INTERVAL
PONG_TIMEOUT = IRC_PONG_TIMEOUT
RATE_LIMIT_MAX = 5
RATE_LIMIT_WINDOW = 60
CONNECT_TIMEOUT = 30
GC_INTERVAL = 300            # GC do rate limit dict a cada 5 minutos


def rate_limit_key(source_full: str) -> str:
    """
    Chave estável para rate limit, baseada no ident@host (não no nick).
    Sobrevive a /nick rotation. Função pública para permitir testes.
    """
    if "!" in source_full:
        return source_full.split("!", 1)[1].lower()
    return source_full.lower()


class RateLimiter:
    """
    Rate limit fixed-window por chave.

    Mantém apenas (count, window_start) por chave — nenhuma task é
    criada por cada comando. A janela expira lazily na próxima
    consulta ou via GC periódico.
    """
    def __init__(self, max_per_window: int, window_seconds: int):
        self.max = max_per_window
        self.window = window_seconds
        self._buckets: dict[str, tuple[int, float]] = {}

    def check_and_increment(self, key: str) -> bool:
        """Devolve True se o pedido é permitido, False se excedeu o limite."""
        now = time.time()
        entry = self._buckets.get(key)

        if entry is None or now - entry[1] > self.window:
            self._buckets[key] = (1, now)
            return True

        count, window_start = entry
        if count >= self.max:
            return False

        self._buckets[key] = (count + 1, window_start)
        return True

    def gc(self) -> int:
        """Remove buckets expirados. Devolve nº removidos."""
        now = time.time()
        expired = [
            k for k, (_, ws) in self._buckets.items()
            if now - ws > self.window
        ]
        for k in expired:
            self._buckets.pop(k, None)
        return len(expired)


class IRCBot:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        logger.info("Inicializando o bot IRC.")
        self.loop = loop
        self.reactor = irc.client.Reactor()
        self.rate_limiter = RateLimiter(RATE_LIMIT_MAX, RATE_LIMIT_WINDOW)
        self.running = True
        self.connection: irc.client.ServerConnection | None = None
        self._last_self_ping = 0.0
        self._last_pong = 0.0
        self._awaiting_pong = False
        self._heartbeat_reconnect_scheduled = False
        self._monitored_bot_nicks = {n.lower() for n in IRC_MONITORED_BOTS}
        self._last_gc = 0.0
        self._reconnecting = False
        self._telegram_controller: TelegramController | None = None
        self._telegram_task: asyncio.Task | None = None
        self.started_at = time.time()
        self.reconnect_count = 0
        self.exit_code = 0
        self.joined_channels: set[str] = set()
        self.last_disconnect_reason = ""

        self._setup_handlers()
        self._connect()

    def _ssl_wrapper(self, sock: socket.socket) -> ssl.SSLSocket:
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            if hasattr(socket, "TCP_KEEPIDLE"):
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 30)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 4)
        except OSError as e:
            logger.warning(f"Não foi possível configurar TCP keepalive: {e}")

        sock.settimeout(CONNECT_TIMEOUT)
        ctx = ssl.create_default_context()
        wrapped = ctx.wrap_socket(sock, server_hostname=SERVER)
        wrapped.settimeout(None)
        return wrapped

    def _setup_handlers(self) -> None:
        handlers = [
            ("welcome", self.on_welcome),
            ("pubmsg", self.on_pubmsg),
            ("privmsg", self.on_privmsg),
            ("join", self.on_join),
            ("part", self.on_part),
            ("quit", self.on_quit),
            ("nick", self.on_nick),
            ("kick", self.on_kick),
            ("pong", self.on_pong),
            ("nicknameinuse", self.on_nickname_in_use),
            ("disconnect", self.on_disconnect),
        ]
        for event_name, handler in handlers:
            self.reactor.add_global_handler(event_name, handler)

    def _connect(self) -> None:
        if self.connection is not None:
            try:
                if self.connection.is_connected():
                    self.connection.disconnect("Reconnecting")
            except Exception:
                pass

        factory = irc.connection.Factory(wrapper=self._ssl_wrapper)

        if self.connection is None:
            self.connection = self.reactor.server()

        self.connection.connect(SERVER, PORT, NICK, connect_factory=factory)
        now = time.time()
        self._last_self_ping = now
        self._last_pong = now
        self._awaiting_pong = False
        self._heartbeat_reconnect_scheduled = False

    def _schedule(self, coro) -> None:
        try:
            self.loop.create_task(coro)
        except RuntimeError:
            coro.close()

    def start_telegram_controller(self) -> None:
        """Arranca o polling Telegram em background, se estiver configurado."""
        self._telegram_controller = TelegramController(self)
        if self._telegram_controller.enabled:
            self._telegram_task = self.loop.create_task(
                self._telegram_controller.run()
            )

    # ───────── Event handlers ─────────

    def on_nickname_in_use(self, connection, event):
        new_nick = NICK + "_"
        logger.warning(f"Nick em uso. A tentar com '{new_nick}'.")
        connection.nick(new_nick)

    def on_welcome(self, connection, event):
        logger.info("Ligado com sucesso ao servidor IRC.")
        now = time.time()
        self._last_self_ping = now
        self._last_pong = now
        self._awaiting_pong = False
        self._heartbeat_reconnect_scheduled = False
        self.last_disconnect_reason = ""
        if PASSWORD:
            connection.privmsg("NickServ", f"IDENTIFY {NICK} {PASSWORD}")
        for canal in CANAIS:
            logger.info(f"A entrar no canal: {canal}")
            connection.join(canal)
        self._schedule(enviar_telegram("✅ O bot ligou-se com sucesso ao IRC."))

    def on_disconnect(self, connection, event):
        self.joined_channels.clear()
        motivo = event.arguments[0] if getattr(event, "arguments", None) else "disconnect event"
        self.last_disconnect_reason = str(motivo)
        logger.warning("Desconectado do servidor: %s", motivo)
        if self._reconnecting:
            logger.debug("Reconexão já em curso — ignorar disconnect duplicado.")
            return
        self._schedule(
            enviar_telegram(
                f"⚠️ O bot foi desconectado do servidor IRC "
                f"(<i>{h(str(motivo))}</i>)."
            )
        )
        self._schedule(self.reconectar())

    async def reconectar(self, tentativas: int = 10) -> None:
        if self._reconnecting:
            return
        self._reconnecting = True
        try:
            for tentativa in range(1, tentativas + 1):
                espera = min(5 * tentativa, 60)
                logger.info(
                    f"Tentativa de reconexão {tentativa}/{tentativas} "
                    f"em {espera}s..."
                )
                await asyncio.sleep(espera)
                try:
                    await asyncio.wait_for(
                        self.loop.run_in_executor(None, self._connect),
                        timeout=CONNECT_TIMEOUT,
                    )
                    self.reconnect_count += 1
                    logger.info("Reconexão estabelecida (a aguardar welcome).")
                    return
                except asyncio.TimeoutError:
                    logger.error(
                        f"Timeout ({CONNECT_TIMEOUT}s) ao tentar reconectar."
                    )
                except Exception as e:
                    logger.error(f"Erro ao reconectar: {e}")

            logger.error("Falha definitiva ao reconectar — a encerrar bot.")
            await enviar_telegram(
                "❌ Falha ao reconectar após várias tentativas."
            )
            self.running = False
        finally:
            self._reconnecting = False

    def on_pubmsg(self, connection, event):
        source_nick = event.source.nick
        source_full = str(event.source)
        target = event.target
        message = event.arguments[0]
        logger.debug(f"<{source_nick}@{target}> {message}")

        self._schedule(log_seen_async(source_nick))

        if message.startswith("!"):
            self._handle_command(source_nick, source_full, message, target)

    def on_privmsg(self, connection, event):
        source_nick = event.source.nick
        source_full = str(event.source)
        message = event.arguments[0]
        logger.debug(f"<{source_nick}> (privado) {message}")

        if message.startswith("!"):
            self._handle_command(source_nick, source_full, message, source_nick)

    def _handle_command(
        self, source_nick: str, source_full: str, message: str, target: str
    ) -> None:
        # Rate limit chaveado pelo ident@host
        rl_key = rate_limit_key(source_full)
        if not self.rate_limiter.check_and_increment(rl_key):
            logger.debug(
                f"Rate limit atingido por {source_nick} ({rl_key})."
            )
            return

        partes = message.split()
        comando = partes[0].lower()
        args = partes[1:]

        # INFO: visibilidade operacional, sem dados sensíveis
        logger.info(f"Comando '{comando}' de {source_nick} em {target}")
        # DEBUG: forensics — hostmask completo + args literais
        logger.debug(
            f"Detalhe: comando={comando} hostmask={source_full} args={args}"
        )

        self._schedule(
            executar_comando(self, source_nick, source_full, comando, args, target)
        )

    def _is_monitored_bot(self, nick: str | None) -> bool:
        if not nick:
            return False
        current = self.connection.get_nickname() if self.connection else NICK
        return nick.lower() == str(current).lower() or nick.lower() in self._monitored_bot_nicks

    def _is_ping_timeout(self, motivo: str | None) -> bool:
        return "ping timeout" in (motivo or "").lower()

    def on_pong(self, connection, event):
        self._last_pong = time.time()
        self._awaiting_pong = False
        self._heartbeat_reconnect_scheduled = False
        logger.debug("PONG recebido do servidor.")

    def on_join(self, connection, event):
        nick = event.source.nick
        canal = event.target
        logger.debug(f"{nick} entrou em {canal}")

        if nick == connection.get_nickname():
            self.joined_channels.add(canal)
            return

        self._schedule(log_seen_async(nick))

        # Boas-vindas: só envia se o nick passar validação
        if canal in BOAS_VINDAS:
            try:
                clean_nick = valid_nick(nick)
            except IRCValidationError:
                logger.warning(
                    f"Nick inválido para boas-vindas, ignorando: {nick!r}"
                )
            else:
                try:
                    self.message(canal, BOAS_VINDAS[canal].format(nick=clean_nick))
                except Exception as e:
                    logger.error(f"Erro ao enviar mensagem de boas-vindas: {e}")

        if canal in CANAIS_COM_ALERTAS:
            self._schedule(
                enviar_telegram(
                    f"👤 <b>{h(nick)}</b> entrou em <b>{h(canal)}</b>."
                )
            )

    def on_part(self, connection, event):
        nick = event.source.nick
        canal = event.target
        logger.debug(f"{nick} saiu de {canal}")

        if self._is_monitored_bot(nick):
            self.joined_channels.discard(canal)
            self._schedule(
                enviar_telegram(
                    f"👋 Bot monitorizado <b>{h(nick)}</b> saiu do canal "
                    f"<b>{h(canal)}</b>."
                )
            )
            return

        self._schedule(log_seen_async(nick))

        if canal in CANAIS_COM_ALERTAS:
            self._schedule(
                enviar_telegram(
                    f"🚪 <b>{h(nick)}</b> saiu de <b>{h(canal)}</b>."
                )
            )

    def on_kick(self, connection, event):
        canal = event.target
        alvo = event.arguments[0] if event.arguments else ""
        motivo = event.arguments[1] if len(event.arguments) > 1 else "(sem motivo)"

        if self._is_monitored_bot(alvo):
            self.joined_channels.discard(canal)
            logger.warning("Bot monitorizado %s expulso de %s: %s", alvo, canal, motivo)
            self._schedule(
                enviar_telegram(
                    f"⚠️ Bot monitorizado <b>{h(alvo)}</b> foi expulso de "
                    f"<b>{h(canal)}</b> (<i>{h(motivo)}</i>)."
                )
            )

    def on_quit(self, connection, event):
        nick = event.source.nick
        motivo = event.arguments[0] if event.arguments else "(sem motivo)"
        logger.info(f"{nick} saiu do servidor: {motivo}")

        if self._is_monitored_bot(nick):
            texto = (
                f"🚨 Bot monitorizado <b>{h(nick)}</b> caiu por "
                f"<b>Ping timeout</b> (<i>{h(motivo)}</i>)."
                if self._is_ping_timeout(motivo)
                else f"⚠️ Bot monitorizado <b>{h(nick)}</b> desligou-se do servidor "
                     f"(<i>{h(motivo)}</i>)."
            )
            self._schedule(enviar_telegram(texto))
            return

        self._schedule(log_seen_async(nick))

        if CANAIS_COM_ALERTAS:
            prefixo = "🚨 Ping timeout" if self._is_ping_timeout(motivo) else "⚠️"
            self._schedule(
                enviar_telegram(
                    f"{prefixo}: <b>{h(nick)}</b> desligou-se do servidor "
                    f"(<i>{h(motivo)}</i>)."
                )
            )

    def on_nick(self, connection, event):
        old_nick = event.source.nick
        new_nick = event.target
        logger.debug(f"Nick: {old_nick} → {new_nick}")
        self._schedule(log_seen_async(old_nick))
        self._schedule(log_seen_async(new_nick))

    # ───────── Acções públicas ─────────

    def message(self, target: str, text: str) -> None:
        try:
            logger.info(f"→ {target}: {text}")
            self.connection.privmsg(target, text)
        except Exception as e:
            logger.error(f"Erro ao enviar msg para {target}: {e}")

    def stop(self, reason: str = "") -> None:
        logger.info("A encerrar o bot... %s", reason)
        self.running = False
        if self._telegram_controller:
            self._telegram_controller.stop()
        try:
            if self.connection and self.connection.is_connected():
                self.connection.quit("Bot encerrado.")
        except Exception as e:
            logger.error(f"Erro ao encerrar conexão IRC: {e}")

    def request_restart(self) -> None:
        """Encerra o processo para o supervisor/systemd o relançar."""
        self.exit_code = 75
        self.stop(reason="restart solicitado")

    def schedule_force_reconnect(self, reason: str = "") -> None:
        self._schedule(self.force_reconnect(reason=reason))

    async def force_reconnect(self, reason: str = "") -> None:
        """Força reconexão IRC imediata, sem esperar pelo backoff normal."""
        if self._reconnecting:
            logger.info("Pedido de force_reconnect ignorado: reconexão já em curso.")
            await enviar_telegram("ℹ️ Reconexão já está em curso.")
            return

        logger.warning("Reconexão forçada. %s", reason)
        await enviar_telegram("🔄 Reconexão IRC forçada por Telegram.")
        self._reconnecting = True
        try:
            await asyncio.wait_for(
                self.loop.run_in_executor(None, self._connect),
                timeout=CONNECT_TIMEOUT,
            )
            self.reconnect_count += 1
        except Exception as e:
            logger.error("Falha na reconexão forçada: %s", e)
            await enviar_telegram(
                f"❌ Falha na reconexão forçada: <code>{h(str(e))}</code>"
            )
        finally:
            self._reconnecting = False

    def _format_uptime(self) -> str:
        seconds = int(time.time() - self.started_at)
        hours, rem = divmod(seconds, 3600)
        minutes, seconds = divmod(rem, 60)
        return f"{hours:02d}h{minutes:02d}m{seconds:02d}s"

    def status_text(self, compact: bool = True) -> str:
        connected = bool(self.connection and self.connection.is_connected())
        last_ping_age = int(time.time() - self._last_self_ping) if self._last_self_ping else -1
        lines = [
            "<b>Estado do Bot IRC</b>",
            f"Processo: {'online' if self.running else 'a encerrar'}",
            f"IRC: {'ligado' if connected else 'desligado'}",
            f"Uptime: {self._format_uptime()}",
            f"Reconexões: {self.reconnect_count}",
        ]
        if not compact:
            lines.extend([
                f"Último auto-ping: há {last_ping_age}s",
                f"Último PONG: há {int(time.time() - self._last_pong) if self._last_pong else -1}s",
                f"A aguardar PONG: {'sim' if self._awaiting_pong else 'não'}",
                f"Bots monitorizados: {h(', '.join(IRC_MONITORED_BOTS) or '-')}",
                f"Canais configurados: {h(', '.join(CANAIS) or '-')}",
                f"Canais activos: {h(', '.join(sorted(self.joined_channels)) or '-')}",
                f"Última falha: {h(self.last_disconnect_reason or '-')}",
            ])
        return "\n".join(lines)

    def channels_text(self) -> str:
        configured = ", ".join(CANAIS) or "-"
        active = ", ".join(sorted(self.joined_channels)) or "-"
        alerts = ", ".join(CANAIS_COM_ALERTAS) or "-"
        return (
            "<b>Canais</b>\n"
            f"Configurados: {h(configured)}\n"
            f"Activos: {h(active)}\n"
            f"Com alertas: {h(alerts)}"
        )

    async def start(self) -> None:
        logger.info("Iniciando o loop do bot.")
        self._last_gc = time.time()

        while self.running:
            try:
                self.reactor.process_once(timeout=0.1)
            except Exception:
                logger.exception("Erro no reactor.")

            now = time.time()

            # Heartbeat activo: envia PING e valida se chega PONG.
            # Isto cobre casos em que a ligação fica meio-aberta e o servidor
            # acabaria por expulsar o nick com "Ping timeout: xxx seconds".
            if now - self._last_self_ping > PING_INTERVAL:
                try:
                    if self.connection and self.connection.is_connected():
                        self.connection.ping(SERVER)
                        self._awaiting_pong = True
                        logger.debug("Auto-PING enviado ao servidor.")
                except Exception as e:
                    logger.warning(f"Falha ao enviar auto-ping: {e}")
                self._last_self_ping = now

            if (
                self._awaiting_pong
                and not self._heartbeat_reconnect_scheduled
                and now - self._last_self_ping > PONG_TIMEOUT
            ):
                self._heartbeat_reconnect_scheduled = True
                self.last_disconnect_reason = f"PONG timeout após {PONG_TIMEOUT}s"
                logger.warning(self.last_disconnect_reason)
                self._schedule(
                    enviar_telegram(
                        f"🚨 O bot não recebeu PONG do servidor após "
                        f"<b>{PONG_TIMEOUT}s</b>. A forçar reconexão."
                    )
                )
                self.schedule_force_reconnect(reason=self.last_disconnect_reason)

            # GC do rate limit dict
            if now - self._last_gc > GC_INTERVAL:
                removed = self.rate_limiter.gc()
                if removed:
                    logger.debug(f"Rate limit GC: {removed} entrada(s) removida(s)")
                self._last_gc = now

            await asyncio.sleep(0)

    # ───────── Comandos IRC (usados pelos plugins) ─────────

    async def set_mode(self, canal: str, modo: str, nick: str) -> None:
        logger.info(f"MODE {canal} {modo} {nick}")
        self.connection.mode(canal, f"{modo} {nick}")

    async def kick(self, canal: str, nick: str, motivo: str = "") -> None:
        logger.info(f"KICK {nick} de {canal} ({motivo})")
        self.connection.kick(canal, nick, motivo)

    async def invite(self, nick: str, canal: str) -> None:
        logger.info(f"INVITE {nick} → {canal}")
        self.connection.invite(nick, canal)

    async def set_topic(self, canal: str, topico: str) -> None:
        logger.info(f"TOPIC {canal}: {topico}")
        self.connection.topic(canal, topico)


# ───────── Entry point ─────────

async def main() -> int:
    init_db()
    loop = asyncio.get_running_loop()
    bot = IRCBot(loop)
    bot.start_telegram_controller()

    async def shutdown():
        logger.info("Sinal de encerramento recebido.")
        try:
            await enviar_telegram("⚠️ O bot foi encerrado.")
        except Exception as e:
            logger.error(f"Erro ao notificar Telegram no encerramento: {e}")
        bot.stop(reason="sinal de encerramento")

    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig, lambda: asyncio.create_task(shutdown())
            )
    else:
        def _win_handler(signum, frame):
            bot.stop(reason="sinal Windows")

        signal.signal(signal.SIGINT, _win_handler)
        signal.signal(signal.SIGTERM, _win_handler)

    logger.info("Bot em execução. Pressiona CTRL+C para sair.")
    try:
        await bot.start()
    finally:
        await asyncio.sleep(1)

        pending = [
            t for t in asyncio.all_tasks(loop)
            if t is not asyncio.current_task()
        ]
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        try:
            await close_http_sessions()
        except Exception as e:
            logger.error(f"Erro ao fechar sessões HTTP: {e}")

    return bot.exit_code


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception:
        logger.exception("Erro inesperado.")
        sys.exit(1)
