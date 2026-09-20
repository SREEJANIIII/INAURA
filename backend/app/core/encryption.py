import base64
import hashlib
from functools import lru_cache
from cryptography.fernet import Fernet
from .config import get_settings


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    settings = get_settings()
    raw_secret = (
        settings.notion_token_encryption_key
        or settings.notion_client_secret
        or settings.supabase_jwt_secret
        or "inaura-default-development-encryption-key-32b"
    )
    # Derive a 32-byte key using SHA-256 and urlsafe base64
    key = base64.urlsafe_b64encode(hashlib.sha256(raw_secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_token(token: str) -> str:
    """Encrypt a sensitive token string at rest."""
    if not token:
        return ""
    fernet = _get_fernet()
    return fernet.encrypt(token.encode("utf-8")).decode("utf-8")


def decrypt_token(encrypted_token: str) -> str:
    """Decrypt a ciphertext token string back to plaintext."""
    if not encrypted_token:
        return ""
    fernet = _get_fernet()
    return fernet.decrypt(encrypted_token.encode("utf-8")).decode("utf-8")
