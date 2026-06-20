# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Osvaldo Cipriano (github.com/nunchuckcoder)
"""
Persistência da última vez que cada utilizador foi visto.
"""

import asyncio
import sqlite3
from datetime import datetime, timezone
from threading import Lock

from config import DATA_DIR

DB_PATH = DATA_DIR / "seen.db"

_lock = Lock()


def init_db() -> None:
    """Cria a tabela 'seen' se ainda não existir."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS seen ("
            "    nick TEXT PRIMARY KEY,"
            "    last_seen TEXT NOT NULL"
            ")"
        )
        conn.commit()


def log_seen(nick: str) -> None:
    """Versão síncrona — usar log_seen_async a partir do event loop."""
    if not nick:
        return

    nick_l = nick.lower()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with _lock:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO seen (nick, last_seen) VALUES (?, ?)",
                (nick_l, now),
            )
            conn.commit()


def get_seen(nick: str) -> str:
    """Versão síncrona — usar get_seen_async a partir do event loop."""
    if not nick:
        return "ℹ️ Nick inválido."

    nick_l = nick.lower()

    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT last_seen FROM seen WHERE nick = ?",
            (nick_l,),
        ).fetchone()

    if row:
        return f"{nick} foi visto pela última vez em {row[0]} (UTC)"

    return f"{nick} nunca foi visto."


async def log_seen_async(nick: str) -> None:
    """Não bloqueia o event loop."""
    if not nick:
        return

    await asyncio.to_thread(log_seen, nick)


async def get_seen_async(nick: str) -> str:
    """Não bloqueia o event loop."""
    if not nick:
        return "ℹ️ Nick inválido."

    return await asyncio.to_thread(get_seen, nick)