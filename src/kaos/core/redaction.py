"""Secret redaction: mask credentials before they leave KAOS.

Pure text utility used by agents to scrub secrets (seed phrases, private keys,
API tokens, passwords) from transcripts sent to LLM providers and from the
artifacts that get published.
"""

from __future__ import annotations

import re

REDACTED = "[REDACTED]"

# Order matters: more specific patterns first.
_PEM_BLOCK = re.compile(r"-----BEGIN [^-]+-----.*?-----END [^-]+-----", re.DOTALL)
_GITHUB_FINE = re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b")
_GITHUB_CLASSIC = re.compile(r"\bghp_[A-Za-z0-9]{36}\b")
_OPENAI = re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")
_DISCORD = re.compile(r"\b[MNO][A-Za-z0-9._-]{22,}\.[A-Za-z0-9._-]{5,}\.[A-Za-z0-9._-]{20,}\b")
_HEX_KEY = re.compile(r"\b(?:0x)?[a-fA-F0-9]{64}\b")

# 12–24 word mnemonic following a seed/recovery-phrase label.
_SEED_PHRASE = re.compile(
    r"(?i)(frase (?:secreta|semilla)|seed(?: phrase)?|recovery phrase|mnemonic|"
    r"palabras de recuperaci[oó]n)\s*[:=]?\s*"
    r"((?:[a-zA-Z]{2,}[ ,]+){11,23}[a-zA-Z]{2,})"
)

# key: value / key = value where the key name is sensitive.
_LABELED = re.compile(
    r"(?i)\b(password|contrase[nñ]a|passphrase|secret|token|api[_-]?key|"
    r"private[_ ]?key|clave privada|seed)\b\s*[:=]\s*"
    r"(\"[^\"]+\"|'[^']+'|\S+)"
)

_PATTERNS = (_PEM_BLOCK, _GITHUB_FINE, _GITHUB_CLASSIC, _OPENAI, _DISCORD, _HEX_KEY)


def redact_secrets(text: str) -> str:
    """Return ``text`` with detected secrets replaced by ``[REDACTED]``."""
    if not text:
        return text
    result = text
    result = _SEED_PHRASE.sub(lambda m: f"{m.group(1)}: {REDACTED}", result)
    result = _LABELED.sub(lambda m: f"{m.group(1)}: {REDACTED}", result)
    for pattern in _PATTERNS:
        result = pattern.sub(REDACTED, result)
    return result

