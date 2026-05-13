"""Symmetric encryption helpers for storing third-party tokens at rest."""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

class TokenCipherError(RuntimeError):
    """Raised when the encryption key is missing/invalid or a token cannot be decrypted."""

    pass

@lru_cache(maxsize=1)
def _cipher():
    """Return a cached Fernet instance built from the configured encryption key."""
    settings = get_settings()
    if not settings.encryption_key:
        raise TokenCipherError(
            "ENCRYPTION_KEY is empty. Generate one: "
            "`python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`"
        )
    try:
        return Fernet(settings.encryption_key.encode() if isinstance(settings.encryption_key, str) else settings.encryption_key)
    except (ValueError, TypeError) as exc:
        raise TokenCipherError(f"Invalid ENCRYPTION_KEY: {exc}") from exc

def encrypt(plain):
    """Encrypt a UTF-8 string and return the Fernet ciphertext as a string."""
    return _cipher().encrypt(plain.encode()).decode()

def decrypt(ciphertext):
    """Decrypt a Fernet-ciphertext string back to plaintext, raising on tampering or key mismatch."""
    try:
        return _cipher().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise TokenCipherError("Cannot decrypt token (key changed?)") from exc
