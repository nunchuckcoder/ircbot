# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Osvaldo Cipriano (github.com/nunchuckcoder)
"""
Notificações e utilitários Telegram (opcional).

Correcções nesta versão:
  • Telegram totalmente opcional — se TELEGRAM_BOT_TOKEN ou
    TELEGRAM_CHAT_ID não estiverem definidos, as chamadas a
    enviar_telegram() são silenciosamente ignoradas.
  • Sessão aiohttp partilhada (módulo http_clients) — evita
    handshake SSL repetido a cada notificação.
  • Helper h() para escapar HTML — usar SEMPRE em qualquer dado
    vindo do IRC (nicks, motivos, tópicos, mensagens) antes de
    interpolar num template HTML, senão um nick como '<b>foo'
    rebenta a formatação ou injecta tags.
  • disable_web_page_preview enviado como bool JSON (não string).
  • Tokens redactados em mensagens de erro (defesa em profundidade).
  • Helpers genéricos para Telegram Bot API usados pelo controlo remoto
    via polling: sendMessage para chat específico e getUpdates.
"""
import asyncio
import re
from html import escape as html_escape
from typing import Any

import aiohttp

from logger import logger
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_ENABLED
from plugins.http_clients import get_telegram_session, get_telegram_polling_session

_API_BASE = (
    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    if TELEGRAM_ENABLED
    else ""
)
_SEND_MESSAGE_URL = f"{_API_BASE}/sendMessage" if TELEGRAM_ENABLED else ""
_GET_UPDATES_URL = f"{_API_BASE}/getUpdates" if TELEGRAM_ENABLED else ""

# Padrão para redactar o token em mensagens de erro
_TOKEN_RE = re.compile(r"bot\d+:[A-Za-z0-9_-]+")


def _redact(text: str) -> str:
    """Substitui qualquer token Telegram visível no texto por '<REDACTED>'."""
    return _TOKEN_RE.sub("bot<REDACTED>", text)


def h(text: str | None) -> str:
    """
    Escapa dados não-confiáveis para inserção segura em mensagens HTML.

    Usar SEMPRE para tudo o que venha do IRC:
        await enviar_telegram(f"<b>{h(nick)}</b> entrou em <b>{h(canal)}</b>")
    """
    if text is None:
        return ""
    return html_escape(str(text), quote=False)


async def enviar_telegram(mensagem: str) -> None:
    """Envia uma mensagem HTML para o chat principal configurado."""
    if not TELEGRAM_CHAT_ID:
        logger.debug("Telegram sem TELEGRAM_CHAT_ID — notificação ignorada.")
        return
    await enviar_telegram_chat(TELEGRAM_CHAT_ID, mensagem)


async def enviar_telegram_chat(chat_id: str | int, mensagem: str) -> None:
    """Envia uma mensagem HTML para um chat específico."""
    if not TELEGRAM_ENABLED:
        logger.debug("Telegram desactivado (token/chat_id não definidos).")
        return

    payload = {
        "chat_id": str(chat_id),
        "text": mensagem,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        logger.debug("Enviando mensagem para Telegram chat_id=%s", chat_id)
        session = await get_telegram_session()
        async with session.post(_SEND_MESSAGE_URL, json=payload) as resp:
            if resp.status == 200:
                logger.info("✅ Mensagem enviada para o Telegram.")
            else:
                text = await resp.text()
                logger.error(
                    "❌ Telegram respondeu %d: %s",
                    resp.status,
                    _redact(text)[:300],
                )
    except asyncio.TimeoutError:
        logger.error("⏳ Timeout ao enviar mensagem para o Telegram.")
    except aiohttp.ClientError as e:
        logger.error("❌ Erro de rede ao enviar para Telegram: %s", _redact(str(e)))
    except Exception:
        logger.exception("Erro inesperado ao enviar para Telegram.")


async def get_updates(offset: int | None = None, timeout: int = 30) -> list[dict[str, Any]]:
    """Obtém updates via long-polling da Telegram Bot API."""
    if not TELEGRAM_ENABLED:
        return []

    payload: dict[str, Any] = {
        "timeout": timeout,
        "allowed_updates": ["message"],
    }
    if offset is not None:
        payload["offset"] = offset

    try:
        session = await get_telegram_polling_session()
        async with session.post(_GET_UPDATES_URL, json=payload) as resp:
            text = await resp.text()
            if resp.status != 200:
                logger.error(
                    "❌ getUpdates respondeu %d: %s",
                    resp.status,
                    _redact(text)[:300],
                )
                return []
            data = await resp.json(content_type=None)
            if not data.get("ok"):
                logger.error("❌ getUpdates sem ok=true: %s", _redact(str(data))[:300])
                return []
            return data.get("result", []) or []
    except asyncio.TimeoutError:
        # Normal em long-polling quando não há updates.
        return []
    except aiohttp.ClientError as e:
        logger.error("❌ Erro de rede no getUpdates: %s", _redact(str(e)))
        return []
    except Exception:
        logger.exception("Erro inesperado no getUpdates.")
        return []
