# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Osvaldo Cipriano (github.com/nunchuckcoder)
"""
Validação de input para comandos IRC.

Previne injecção de CRLF — sem isto, um motivo de kick, tópico ou
argumento de mode contendo \\r\\n permitiria a um utilizador injectar
comandos arbitrários no servidor com a identidade do bot
(e.g. fazer o bot enviar um KILL ou um PRIVMSG noutro canal).

Aplica também os limites sintácticos do protocolo IRC (RFC 2812).
"""
import re

# Nick: começa com letra ou special, depois letra/dígito/special/hífen.
# Special = [ ] \ ` _ ^ { | }
# Nota: usar \A e \Z (não ^ e $) para garantir match estrito do início
# ao fim. Em Python, $ por defeito aceita um \n final, o que faria
# valid_nick("Foo\n") passar — anulando a defesa anti-CRLF.
_NICK_RE = re.compile(r"\A[A-Za-z\[\]\\`_^{|}][A-Za-z0-9\[\]\\`_^{|}\-]{0,30}\Z")

# Canal: # & + ! seguido de chars sem control chars, espaço ou vírgula
_CHANNEL_RE = re.compile(r"\A[#&+!][^\x00\x07\r\n, ]{1,49}\Z")

# Caracteres proibidos em texto livre (motivos, tópicos, mensagens)
_TEXT_FORBIDDEN_RE = re.compile(r"[\r\n\x00]")


class IRCValidationError(ValueError):
    """Levantado quando um valor não é válido para envio ao servidor IRC."""


def valid_nick(nick: str) -> str:
    """Devolve o nick se for válido, senão levanta IRCValidationError."""
    if not isinstance(nick, str) or not nick:
        raise IRCValidationError("Nick vazio.")
    if len(nick) > 31:
        raise IRCValidationError(f"Nick demasiado longo: {nick!r}")
    if not _NICK_RE.match(nick):
        raise IRCValidationError(f"Nick inválido: {nick!r}")
    return nick


def valid_channel(channel: str) -> str:
    """Devolve o canal se for válido, senão levanta IRCValidationError."""
    if not isinstance(channel, str) or not channel:
        raise IRCValidationError("Canal vazio.")
    if len(channel) > 50:
        raise IRCValidationError(f"Canal demasiado longo: {channel!r}")
    if not _CHANNEL_RE.match(channel):
        raise IRCValidationError(f"Canal inválido: {channel!r}")
    return channel


def safe_text(text: str, max_len: int = 400) -> str:
    """
    Sanitiza texto livre (motivos de kick, tópicos, mensagens).

    Substitui CR/LF por espaço, remove NUL, e trunca ao tamanho máximo.
    Usado para tudo o que vai para um campo IRC livre depois do ':'.
    """
    if not isinstance(text, str):
        text = str(text)
    cleaned = _TEXT_FORBIDDEN_RE.sub(" ", text)
    return cleaned[:max_len].strip()
