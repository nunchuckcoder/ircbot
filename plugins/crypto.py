# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Osvaldo Cipriano (github.com/nunchuckcoder)
"""
Consulta de preços via API pública da Binance.

v3: Validação rígida do símbolo via regex. "bt c" passa a ser rejeitado
em vez de silenciosamente transformado em "BTC".
"""
import asyncio
import re

import aiohttp

from plugins.http_clients import get_binance_session

# Símbolo aceite: 1-10 chars alfanuméricos.
# Nota: usar \Z (não $) para garantir end-of-string estrito —
# em Python, $ aceita um \n final, o que permitiria 'BTC\n' passar
# e potencialmente injectar CRLF na chamada à API.
_SYMBOL_RE = re.compile(r"\A[A-Za-z0-9]{1,10}\Z")


async def get_crypto_price(symbol: str) -> str:
    if not symbol or not _SYMBOL_RE.match(symbol):
        return "⚠️ Símbolo inválido. Usa apenas letras/números (ex: BTC, ETH)."

    symbol_u = symbol.upper()
    session = await get_binance_session()

    moedas = [
        ("EUR", "💶", "EUR"),
        ("USDT", "💲", "USD"),
    ]

    for par, prefixo, label in moedas:
        url = (
            f"https://api.binance.com/api/v3/ticker/price"
            f"?symbol={symbol_u}{par}"
        )
        try:
            async with session.get(url) as res:
                # Erros transitórios — abortar imediatamente
                if res.status == 429:
                    return "⏳ Rate limit da Binance — tenta mais tarde."
                if res.status >= 500:
                    return f"❌ Binance indisponível (HTTP {res.status})."

                # 200 ou 400 (símbolo inválido) — ambos têm JSON
                try:
                    data = await res.json()
                except Exception:
                    continue  # tentar próxima moeda

                if "price" in data:
                    return f"{prefixo} {symbol_u}: {float(data['price']):.8f} {label}"
                # 400 com 'Invalid symbol' — tentar próxima moeda
        except asyncio.TimeoutError:
            return "⏳ Timeout ao contactar a Binance."
        except aiohttp.ClientError:
            return "❌ Erro de rede ao contactar a Binance."
        except Exception as e:
            return f"⚠️ Erro inesperado: {e}"

    return f"⚠️ Moeda '{symbol_u}' não encontrada."
