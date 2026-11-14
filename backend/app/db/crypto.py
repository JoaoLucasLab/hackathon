"""Encryption at rest for student data (DATA-06): audit JSON and chat messages.

Fernet (AES-128-CBC with an HMAC-SHA256 check) with a key derived from `DATA_KEY`.
Any secret string works as DATA_KEY (`openssl rand -base64 32`): its SHA-256 is the
key. Without DATA_KEY (local dev, tests) the key is random per process, so what was
stored cannot be read after a restart, like sessions without SESSION_SECRET.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app import config

log = logging.getLogger(__name__)


class DecryptError(Exception):
    """Stored data that this DATA_KEY cannot read (another key, or changed bytes)."""


def fernet_for(secret: str) -> Fernet:
    digest = hashlib.sha256(secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    if config.DATA_KEY:
        return fernet_for(config.DATA_KEY)
    if config.DATABASE_URL:
        log.warning("DATA_KEY is not set: stored audits and chats are unreadable after a restart")
    return Fernet(Fernet.generate_key())


def encrypt(text: str) -> bytes:
    return _fernet().encrypt(text.encode())


def decrypt(token: bytes) -> str:
    try:
        return _fernet().decrypt(token).decode()
    except InvalidToken:
        raise DecryptError("stored data cannot be read with this DATA_KEY") from None
