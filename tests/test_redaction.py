"""Tests for the secret redaction utility."""

from __future__ import annotations

from kaos.core.redaction import REDACTED, redact_secrets


def test_empty_text_is_returned_unchanged() -> None:
    assert redact_secrets("") == ""


def test_plain_text_is_left_intact() -> None:
    text = "avanzamos con el módulo Odoo y usaremos PostgreSQL"
    assert redact_secrets(text) == text


def test_seed_phrase_is_redacted() -> None:
    text = (
        "frase secreta: witch collapse practice feed shame open despair "
        "creek road again ice least"
    )
    result = redact_secrets(text)
    assert "witch collapse" not in result
    assert REDACTED in result


def test_english_seed_phrase_label_is_redacted() -> None:
    text = (
        "seed phrase: witch collapse practice feed shame open despair "
        "creek road again ice least"
    )
    result = redact_secrets(text)
    assert "practice feed" not in result
    assert REDACTED in result


def test_labeled_password_is_redacted() -> None:
    assert redact_secrets("password: hunter2") == f"password: {REDACTED}"
    assert redact_secrets("contraseña = s3cr3t") == f"contraseña: {REDACTED}"


def test_openai_key_is_redacted() -> None:
    text = "usa esta api_key sk-abcdefghijklmnopqrstuvwxyz012345 para el provider"
    result = redact_secrets(text)
    assert "sk-abcdefghijklmnopqrstuvwxyz012345" not in result
    assert REDACTED in result


def test_github_tokens_are_redacted() -> None:
    classic = "ghp_" + "a" * 36
    fine = "github_pat_" + "b" * 42
    assert classic not in redact_secrets(f"token {classic}")
    assert fine not in redact_secrets(f"token {fine}")


def test_hex_private_key_is_redacted() -> None:
    key = "0x" + "a1b2c3d4" * 8  # 64 hex chars
    result = redact_secrets(f"private key {key}")
    assert key not in result
    assert REDACTED in result


def test_pem_block_is_redacted() -> None:
    pem = (
        "-----BEGIN PRIVATE KEY-----\n"
        "MIIBVwIBADANBgkqhkiG9w0BAQEFAASCAT\n"
        "-----END PRIVATE KEY-----"
    )
    result = redact_secrets(f"clave:\n{pem}\nfin")
    assert "MIIBVwIBADANBgkqhkiG9w0BAQEFAASCAT" not in result
    assert REDACTED in result


def test_multiple_secrets_in_one_text() -> None:
    text = "password: hunter2 y api_key: sk-abcdefghijklmnopqrstuvwxyz012345"
    result = redact_secrets(text)
    assert "hunter2" not in result
    assert "sk-abcdefghijklmnopqrstuvwxyz012345" not in result
    assert result.count(REDACTED) >= 2

