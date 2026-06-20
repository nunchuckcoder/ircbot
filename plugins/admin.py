# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Osvaldo Cipriano (github.com/nunchuckcoder)
"""
Verificação de privilégios de administrador (apenas hostmask).

⚠️ Admin-by-nick (entradas em IRC_ADMINS sem '!') já não é suportado.
   Era trivialmente contornável por mudança de nick.

Formato aceite: hostmask completa, com wildcards * e ?
   IRC_ADMINS=NickName!*@*.vhost,icub!*@*.vhost
"""
import fnmatch

from logger import logger
from config import ADMINS

# Apenas entradas com hostmask
ADMIN_HOSTMASKS = [a.lower() for a in ADMINS if "!" in a]

# Detectar entradas no formato legado e abortar com erro claro
_nick_only = [a for a in ADMINS if a and "!" not in a]
if _nick_only:
    raise RuntimeError(
        "\n\n"
        "═══════════════════════════════════════════════════════════════════\n"
        "  ❌ Configuração IRC_ADMINS inválida\n"
        "═══════════════════════════════════════════════════════════════════\n"
        f"  Entradas sem hostmask detectadas: {_nick_only}\n"
        "\n"
        "  Admin-by-nick já não é suportado por ser trivialmente\n"
        "  contornável: qualquer utilizador pode mudar de nick para um\n"
        "  destes (e.g. quando o admin verdadeiro está em ping timeout)\n"
        "  e ganhar acesso administrativo ao bot.\n"
        "\n"
        "  Substitui cada entrada por uma hostmask com wildcards. Ex:\n"
        "      IRC_ADMINS=NickName!*@*.vhost,icub!*@*.vhost\n"
        "\n"
        "  Para descobrir a vhost de cada admin, faz no servidor IRC:\n"
        "      /whois <nick>\n"
        "\n"
        "  Se REALMENTE queres aceitar qualquer ligação com esse nick\n"
        "  (não recomendado — equivalente ao modo antigo), usa:\n"
        "      IRC_ADMINS=icub!*@*\n"
        "═══════════════════════════════════════════════════════════════════\n"
    )

if not ADMIN_HOSTMASKS:
    logger.warning(
        "IRC_ADMINS está vazio — nenhum utilizador terá acesso admin."
    )
else:
    logger.info(
        "Admin hostmasks configuradas: %d entrada(s).", len(ADMIN_HOSTMASKS)
    )


# ─────────────── Pure matching function (testável) ───────────────

def matches_any_pattern(source: str, patterns: list[str]) -> bool:
    """
    Função pura: True se source bate em algum padrão fnmatch (case-insensitive).

    Separada do estado do módulo para permitir testes unitários sem
    depender da configuração global. Faz lower-case em ambos os lados
    porque hostmasks IRC são case-insensitive e fnmatch.fnmatch herda
    o case-sensitivity do sistema operativo (sensitive em Linux,
    insensitive em Windows).
    """
    if not source or not patterns:
        return False
    source_l = source.lower()
    return any(fnmatch.fnmatch(source_l, p.lower()) for p in patterns)


# ─────────────── Wrappers que usam a configuração do módulo ───────────────

def is_admin(source: str) -> bool:
    """
    Verifica se um utilizador tem privilégios de admin.

    Args:
        source: hostmask completa 'nick!ident@host'.
    """
    if not source or "!" not in source:
        return False
    return matches_any_pattern(source, ADMIN_HOSTMASKS)


def is_admin_nick(nick: str) -> bool:
    """
    Heurística: verifica se algum padrão admin tem este nick na sua
    parte antes do '!'. Não é uma verificação de segurança — apenas
    indica que o nick aparece na configuração.
    """
    if not nick:
        return False
    pattern_nicks = [p.split("!", 1)[0] for p in ADMIN_HOSTMASKS]
    return matches_any_pattern(nick, pattern_nicks)
