# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Osvaldo Cipriano (github.com/nunchuckcoder)
"""
Sessões aiohttp partilhadas para chamadas HTTP de saída.

Uma única ClientSession por endpoint reutiliza conexões TCP keep-alive
e o ciclo de handshake SSL, em vez de pagar esse custo a cada chamada.

As sessões são criadas lazily na primeira utilização (necessário porque
ClientSession tem de ser construído dentro do event loop) e fechadas
explicitamente no shutdown via close_all().
"""
import aiohttp

_telegram_session: aiohttp.ClientSession | None = None
_telegram_polling_session: aiohttp.ClientSession | None = None
_binance_session: aiohttp.ClientSession | None = None


def _new_session(total_timeout: int = 10) -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=total_timeout),
    )


async def get_telegram_session() -> aiohttp.ClientSession:
    global _telegram_session
    if _telegram_session is None or _telegram_session.closed:
        _telegram_session = _new_session()
    return _telegram_session


async def get_telegram_polling_session() -> aiohttp.ClientSession:
    """Sessão separada para long-polling Telegram, com timeout superior."""
    global _telegram_polling_session
    if _telegram_polling_session is None or _telegram_polling_session.closed:
        _telegram_polling_session = _new_session(total_timeout=45)
    return _telegram_polling_session


async def get_binance_session() -> aiohttp.ClientSession:
    global _binance_session
    if _binance_session is None or _binance_session.closed:
        _binance_session = _new_session()
    return _binance_session


async def close_all() -> None:
    """Fecha todas as sessões — chamar uma vez no shutdown do bot."""
    global _telegram_session, _telegram_polling_session, _binance_session
    for s in (_telegram_session, _telegram_polling_session, _binance_session):
        if s is not None and not s.closed:
            await s.close()
    _telegram_session = None
    _telegram_polling_session = None
    _binance_session = None
