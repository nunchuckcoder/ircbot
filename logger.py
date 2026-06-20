# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Osvaldo Cipriano (github.com/nunchuckcoder)
"""
Configuração de logging com rotação de ficheiros.

Níveis configuráveis via .env:
    LOG_LEVEL_FILE     (default INFO)
    LOG_LEVEL_CONSOLE  (default INFO)
"""
import logging
import os
from logging.handlers import RotatingFileHandler

from config import LOG_DIR

LOG_LEVEL_FILE = os.getenv("LOG_LEVEL_FILE", "INFO").upper()
LOG_LEVEL_CONSOLE = os.getenv("LOG_LEVEL_CONSOLE", "INFO").upper()

LOG_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("BotLogger")
logger.setLevel(logging.DEBUG)
logger.propagate = False

if not logger.handlers:
    fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    file_handler = RotatingFileHandler(
        LOG_DIR / "bot.log",
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(LOG_LEVEL_FILE)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(LOG_LEVEL_CONSOLE)
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)