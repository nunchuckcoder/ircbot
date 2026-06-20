# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Osvaldo Cipriano (github.com/nunchuckcoder)
"""
Despacho de comandos do bot.

v4: !status reformulado para ser claro sobre o que é verificação real
(via hostmask) vs heurística (nick aparece numa hostmask configurada).
"""
from plugins.admin import is_admin, is_admin_nick
from plugins import seen
from plugins.crypto import get_crypto_price
from plugins.irc_validate import (
    valid_nick,
    valid_channel,
    safe_text,
    IRCValidationError,
)


# Comandos administrativos que só fazem sentido executados num canal
CHANNEL_ONLY = {
    "!op", "!up", "!deop", "!down",
    "!voice", "!devoice",
    "!kick", "!k",
    "!ban", "!kb", "!unban",
    "!invite", "!topic",
}


async def executar_comando(
    bot,
    source: str,         # nick (ex: 'NickName')
    source_full: str,    # hostmask completo (ex: 'NickName!~moo@vhost')
    comando: str,
    args: list[str],
    target: str,
):
    canal = target  # destino da resposta

    def sem_permissao() -> None:
        bot.message(canal, "🚫 Sem permissão para executar este comando.")

    def uso(correto: str) -> None:
        bot.message(canal, f"ℹ️ Uso correcto: {correto}")

    def err(msg: str) -> None:
        bot.message(canal, f"❌ {msg}")

    def admin() -> bool:
        return is_admin(source_full)

    # Restringir comandos administrativos de canal a contexto de canal
    if comando in CHANNEL_ONLY and not target.startswith(("#", "&")):
        bot.message(
            canal,
            "❌ Este comando só pode ser usado dentro de um canal.",
        )
        return

    match comando:

        # ───── Op / Voice ─────
        case "!op" | "!up":
            if not admin():
                return sem_permissao()
            try:
                nick = valid_nick(args[0]) if args else valid_nick(source)
            except IRCValidationError as e:
                return err(str(e))
            await bot.set_mode(canal, "+o", nick)

        case "!deop" | "!down":
            if not admin():
                return sem_permissao()
            try:
                nick = valid_nick(args[0]) if args else valid_nick(source)
            except IRCValidationError as e:
                return err(str(e))
            await bot.set_mode(canal, "-o", nick)

        case "!voice":
            if not admin():
                return sem_permissao()
            if not args:
                return uso("!voice <nick>")
            try:
                nick = valid_nick(args[0])
            except IRCValidationError as e:
                return err(str(e))
            await bot.set_mode(canal, "+v", nick)

        case "!devoice":
            if not admin():
                return sem_permissao()
            if not args:
                return uso("!devoice <nick>")
            try:
                nick = valid_nick(args[0])
            except IRCValidationError as e:
                return err(str(e))
            await bot.set_mode(canal, "-v", nick)

        # ───── Kick / Ban ─────
        case "!kick" | "!k":
            if not admin():
                return sem_permissao()
            if not args:
                return uso("!kick <nick> [motivo]")
            try:
                nick = valid_nick(args[0])
            except IRCValidationError as e:
                return err(str(e))
            motivo = safe_text(" ".join(args[1:]), 200) if len(args) > 1 else ""
            await bot.kick(canal, nick, motivo)

        case "!ban" | "!kb":
            if not admin():
                return sem_permissao()
            if not args:
                return uso("!ban <nick> [motivo]")
            try:
                nick = valid_nick(args[0])
            except IRCValidationError as e:
                return err(str(e))
            motivo = safe_text(" ".join(args[1:]), 200) if len(args) > 1 else ""
            await bot.set_mode(canal, "+b", f"{nick}!*@*")
            await bot.kick(canal, nick, motivo)

        case "!unban":
            if not admin():
                return sem_permissao()
            if not args:
                return uso("!unban <nick>")
            try:
                nick = valid_nick(args[0])
            except IRCValidationError as e:
                return err(str(e))
            await bot.set_mode(canal, "-b", f"{nick}!*@*")

        # ───── Canal ─────
        case "!invite":
            if not admin():
                return sem_permissao()
            if not args:
                return uso("!invite <nick>")
            try:
                nick = valid_nick(args[0])
            except IRCValidationError as e:
                return err(str(e))
            await bot.invite(nick, canal)

        case "!topic":
            if not admin():
                return sem_permissao()
            if not args:
                return uso("!topic <novo tópico>")
            await bot.set_topic(canal, safe_text(" ".join(args), 390))

        case "!join":
            if not admin():
                return sem_permissao()
            if not args:
                return uso("!join <#canal>")
            try:
                novo_canal = valid_channel(args[0])
            except IRCValidationError as e:
                return err(str(e))
            bot.connection.join(novo_canal)
            bot.message(canal, f"✅ A entrar em {novo_canal}")

        case "!part":
            if not admin():
                return sem_permissao()
            if not args:
                return uso("!part <#canal>")
            try:
                sair_canal = valid_channel(args[0])
            except IRCValidationError as e:
                return err(str(e))
            # Avisar ANTES de sair (caso seja o canal actual)
            bot.message(canal, f"👋 A sair de {sair_canal}")
            bot.connection.part(sair_canal)

        # ───── Informação ─────
        case "!status":
            # Sem args: verificação REAL pela hostmask do próprio caller
            # Com args: heurística — apenas verifica se o nick aparece em
            # alguma hostmask configurada. Restrito a admins para evitar
            # enumeração da configuração.
            if not args:
                eh_admin = is_admin(source_full)
                bot.message(
                    canal,
                    f"Status: {'Admin ✓' if eh_admin else 'Utilizador comum'}"
                )
            else:
                if not admin():
                    return err(
                        "Apenas admins podem consultar o estado de outros."
                    )
                try:
                    nick = valid_nick(args[0])
                except IRCValidationError as e:
                    return err(str(e))
                aparece = is_admin_nick(nick)
                bot.message(
                    canal,
                    f"Nick '{nick}' aparece numa hostmask admin: "
                    f"{'sim' if aparece else 'não'}. "
                    f"(heurística — verificação real exige hostmask completa)"
                )

        case "!seen":
            if not args:
                return uso("!seen <nick>")
            try:
                nick = valid_nick(args[0])
            except IRCValidationError as e:
                return err(str(e))
            resultado = await seen.get_seen_async(nick)
            bot.message(canal, resultado)

        case "!crypto":
            if not args:
                return uso("!crypto <símbolo>")
            resultado = await get_crypto_price(args[0])
            bot.message(canal, resultado)

        # ───── Ajuda ─────
        case "!ajuda":
            ajuda = [
                ("🤖 Comandos disponíveis:", ""),
                ("!op [nick]", "Dá op (admin, em canal)."),
                ("!deop [nick]", "Remove op (admin, em canal)."),
                ("!voice <nick>", "Dá voz (admin, em canal)."),
                ("!devoice <nick>", "Remove voz (admin, em canal)."),
                ("!kick <nick> [motivo]", "Expulsa (admin, em canal)."),
                ("!ban <nick> [motivo]", "Bane e expulsa (admin, em canal)."),
                ("!kb <nick> [motivo]", "Atalho para !ban (admin, em canal)."),
                ("!unban <nick>", "Remove ban (admin, em canal)."),
                ("!invite <nick>", "Convida (admin, em canal)."),
                ("!topic <texto>", "Altera tópico (admin, em canal)."),
                ("!join <#canal>", "Bot entra num canal (admin, qualquer lado)."),
                ("!part <#canal>", "Bot sai de um canal (admin, qualquer lado)."),
                ("!status [nick]", "Mostra o teu estado real, ou (admin) consulta nick."),
                ("!seen <nick>", "Última vez que o nick foi visto."),
                ("!crypto <símbolo>", "Preço actual de uma criptomoeda."),
            ]
            for cmd, desc in ajuda:
                bot.message(canal, f"{cmd} – {desc}" if desc else cmd)

        # ───── Comando desconhecido ─────
        case _:
            # Em PM respondemos; em canais públicos ignoramos para não fazer spam
            if canal == source:
                bot.message(canal, "❓ Comando desconhecido. Usa !ajuda.")
