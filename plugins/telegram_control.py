# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Osvaldo Cipriano (github.com/nunchuckcoder)
"""
Controlo remoto do bot por Telegram via long-polling.

Comandos suportados:
  /status     Estado operacional resumido
  /health     Estado detalhado
  /channels   Canais configurados e canais onde o bot se viu entrar
  /reconnect  Força reconexão IRC imediata dentro do mesmo processo
  /restart    Encerra o processo para ser relançado pelo supervisor/systemd
  /quit       Encerra o bot de forma controlada
  /help       Ajuda

Correção v4.3.1:
  • Guarda o update_id processado em ficheiro.
  • Usa sempre offset = último update_id + 1.
  • Grava o offset ANTES de executar comandos como /quit ou /restart.
  • No primeiro arranque sem offset gravado, ignora comandos pendentes antigos.
"""

from __future__ import annotations

import asyncio
from typing import Any

from logger import logger
from config import TELEGRAM_ENABLED, TELEGRAM_ADMIN_CHAT_IDS, DATA_DIR
from plugins.telegram import enviar_telegram_chat, get_updates


OFFSET_FILE = DATA_DIR / ".telegram_update_offset"


class TelegramController:
    def __init__(self, bot):
        self.bot = bot
        self._offset: int | None = self._load_offset()
        self._running = False
        self._admins = {str(x) for x in TELEGRAM_ADMIN_CHAT_IDS}

    @property
    def enabled(self) -> bool:
        return TELEGRAM_ENABLED and bool(self._admins)

    def _load_offset(self) -> int | None:
        try:
            if not OFFSET_FILE.exists():
                return None

            value = OFFSET_FILE.read_text(encoding="utf-8").strip()
            if not value:
                return None

            offset = int(value)
            if offset < 0:
                return None

            return offset
        except Exception:
            logger.warning("Não foi possível ler o offset Telegram guardado.", exc_info=True)
            return None

    def _save_offset(self, offset: int) -> None:
        try:
            tmp_file = OFFSET_FILE.with_suffix(".tmp")
            tmp_file.write_text(str(offset), encoding="utf-8")
            tmp_file.replace(OFFSET_FILE)
        except Exception:
            logger.warning("Não foi possível guardar o offset Telegram.", exc_info=True)

    async def _discard_pending_updates_on_first_start(self) -> None:
        """
        Evita executar comandos antigos quando o bot arranca sem offset guardado.

        Isto é importante porque o Telegram mantém updates pendentes até serem
        confirmados por offset. Se o último comando tiver sido /quit, o bot podia
        entrar num ciclo infinito de arranque -> /quit -> arranque.
        """
        if self._offset is not None:
            return

        try:
            updates = await get_updates(offset=-1, timeout=0)

            if not updates:
                logger.info("Telegram sem comandos pendentes antigos.")
                self._offset = 0
                self._save_offset(self._offset)
                return

            max_update_id = max(
                update.get("update_id", -1)
                for update in updates
                if isinstance(update.get("update_id"), int)
            )

            if max_update_id >= 0:
                self._offset = max_update_id + 1
                self._save_offset(self._offset)
                logger.info(
                    "Ignorados comandos Telegram pendentes até update_id=%s.",
                    max_update_id,
                )
            else:
                self._offset = 0
                self._save_offset(self._offset)

        except Exception:
            logger.warning(
                "Falha ao limpar comandos Telegram pendentes no arranque.",
                exc_info=True,
            )

    async def run(self) -> None:
        if not self.enabled:
            logger.info(
                "Controlo Telegram desactivado: token ausente ou sem admins."
            )
            return

        self._running = True
        logger.info("Controlo Telegram activo para %d chat_id(s).", len(self._admins))

        await self._discard_pending_updates_on_first_start()

        while self._running and self.bot.running:
            updates = await get_updates(offset=self._offset, timeout=30)

            for update in updates:
                update_id = update.get("update_id")

                if isinstance(update_id, int):
                    next_offset = update_id + 1

                    # Guardar ANTES de executar o comando.
                    # Assim, se o comando for /quit ou /restart, este update
                    # já fica confirmado e não volta a ser executado no arranque.
                    self._offset = next_offset
                    self._save_offset(next_offset)

                await self._handle_update(update)

            await asyncio.sleep(0)

    def stop(self) -> None:
        self._running = False

    async def _handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        text = (message.get("text") or "").strip()

        if not chat_id or not text.startswith("/"):
            return

        if chat_id not in self._admins:
            logger.warning("Comando Telegram rejeitado de chat_id=%s", chat_id)
            await enviar_telegram_chat(
                chat_id,
                "🚫 Este chat não está autorizado a controlar o bot.",
            )
            return

        command = text.split()[0].split("@", 1)[0].lower()
        logger.info("Comando Telegram recebido: %s", command)

        match command:
            case "/start" | "/help":
                await self._reply_help(chat_id)

            case "/status":
                await enviar_telegram_chat(
                    chat_id,
                    self.bot.status_text(compact=True),
                )

            case "/health":
                await enviar_telegram_chat(
                    chat_id,
                    self.bot.status_text(compact=False),
                )

            case "/channels":
                await enviar_telegram_chat(
                    chat_id,
                    self.bot.channels_text(),
                )

            case "/reconnect":
                await enviar_telegram_chat(
                    chat_id,
                    "🔄 A forçar reconexão IRC imediata...",
                )
                self.bot.schedule_force_reconnect(
                    reason="Comando Telegram /reconnect"
                )

            case "/restart":
                await enviar_telegram_chat(
                    chat_id,
                    "♻️ A encerrar para restart pelo supervisor/systemd...",
                )
                self.bot.request_restart()

            case "/quit":
                await enviar_telegram_chat(
                    chat_id,
                    "👋 A encerrar o bot...",
                )
                self.bot.stop(reason="Comando Telegram /quit")

            case _:
                await enviar_telegram_chat(
                    chat_id,
                    "❓ Comando desconhecido. Usa /help.",
                )

    async def _reply_help(self, chat_id: str) -> None:
        await enviar_telegram_chat(
            chat_id,
            "<b>Comandos Telegram</b>\n"
            "/status — estado resumido\n"
            "/health — estado detalhado\n"
            "/channels — canais configurados/activos\n"
            "/reconnect — força reconexão IRC\n"
            "/restart — encerra para restart pelo systemd/supervisor\n"
            "/quit — encerra o bot\n"
            "/help — mostra esta ajuda",
        )