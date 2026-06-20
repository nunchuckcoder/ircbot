# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Osvaldo Cipriano (github.com/nunchuckcoder)
"""
Configuração do bot IRC.

Variáveis sensíveis lidas exclusivamente do .env. Sem credenciais hardcoded.
Variáveis obrigatórias rebentam o arranque (fail-fast).

Obrigatórias: IRC_NICK, IRC_SERVER, IRC_PORT
Opcionais:    IRC_PASSWORD (NickServ),
              TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID (notificações),
              IRC_ADMINS, CANAIS, CANAIS_COM_ALERTAS
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

DATA_DIR = Path(os.getenv("BOT_DATA_DIR", BASE_DIR / "data"))
LOG_DIR = Path(os.getenv("BOT_LOG_DIR", DATA_DIR / "logs"))

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _required(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(
            f"Variável de ambiente obrigatória '{name}' não está definida. "
            "Verifica o ficheiro .env (ver .env.example para template)."
        )
    return val


# ────────── Ligação IRC ──────────
NICK = _required("IRC_NICK")
SERVER = _required("IRC_SERVER")
PORT = int(_required("IRC_PORT"))

# Opcional — para servidores sem NickServ, deixar vazio
PASSWORD = os.getenv("IRC_PASSWORD", "").strip()

# ────────── Telegram (opcional) ──────────
# Se ambos estiverem definidos, notificações são enviadas.
# Se um (ou ambos) faltar, são silenciosamente ignoradas.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# Lista de chat_ids autorizados a controlar o bot por Telegram.
# Se vazio, usa TELEGRAM_CHAT_ID como único admin por defeito.
TELEGRAM_ADMIN_CHAT_IDS = [
    x.strip()
    for x in os.getenv("TELEGRAM_ADMIN_CHAT_IDS", TELEGRAM_CHAT_ID).split(",")
    if x.strip()
]

# O Telegram fica activo se existir token. Para notificações é também
# necessário TELEGRAM_CHAT_ID; para controlo remoto são necessários admins.
TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN)

# ────────── Monitorização / watchdog IRC ──────────
# Nicks de bots a monitorizar no IRC. Quando estes nicks saem por PART,
# QUIT, KICK ou Ping timeout, é enviado alerta Telegram. Por defeito,
# monitoriza o próprio nick configurado em IRC_NICK.
_monitored_bots_raw = os.getenv("IRC_MONITORED_BOTS", "").strip()
if not _monitored_bots_raw:
    _monitored_bots_raw = NICK
IRC_MONITORED_BOTS = [
    n.strip()
    for n in _monitored_bots_raw.split(",")
    if n.strip()
]

# Heartbeat activo: o bot envia PING periódico ao servidor e força reconnect
# se não receber PONG dentro do tempo configurado.
IRC_PING_INTERVAL = int(os.getenv("IRC_PING_INTERVAL", "120"))
IRC_PONG_TIMEOUT = int(os.getenv("IRC_PONG_TIMEOUT", "45"))

# ────────── Canais ──────────
CANAIS = [
    c.strip()
    for c in os.getenv(
        "CANAIS",
        "#portugal,#informática,#cybersecurity",
    ).split(",")
    if c.strip()
]

CANAIS_COM_ALERTAS = [
    c.strip()
    for c in os.getenv("CANAIS_COM_ALERTAS", ",".join(CANAIS)).split(",")
    if c.strip()
]

# ────────── Administradores ──────────
# Formato recomendado: hostmask completa nick!ident@host (com wildcards * ?)
#   Exemplo seguro:    NickName!*@*.vhost
#   Exemplo legado:    NickName   (apenas nick — vulnerável a spoofing)
ADMINS = [
    a.strip()
    for a in os.getenv("IRC_ADMINS", "").split(",")
    if a.strip()
]

# ────────── Mensagens de boas-vindas ──────────
BOAS_VINDAS = {
    "#informática": "💻 Bem-vindo(a) ao #informática, {nick}! Tecnologia, programação, Linux, redes e ajuda entre todos. 🚀",
    "#cybersecurity": "🛡️ Bem-vindo(a) ao #cybersecurity, {nick}! Segurança informática, hacking ético, privacidade e conhecimento técnico. 🔐",
}
