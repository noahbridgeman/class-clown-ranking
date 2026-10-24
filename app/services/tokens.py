"""One-time link tokens. The link carries a signed random nonce, the database only its hash."""

import hashlib
import secrets

from flask import current_app
from itsdangerous import BadSignature, URLSafeSerializer


def new_nonce() -> str:
    return secrets.token_urlsafe(32)


def hash_nonce(nonce: str) -> str:
    return hashlib.sha256(nonce.encode()).hexdigest()


def sign(nonce: str, salt: str) -> str:
    return _serializer(salt).dumps(nonce)


def unsign(link_token: str, salt: str) -> str | None:
    """The nonce of a link token, or None if the signature or payload is wrong."""
    try:
        nonce = _serializer(salt).loads(link_token)
    except BadSignature:
        return None
    return nonce if isinstance(nonce, str) else None


def _serializer(salt: str) -> URLSafeSerializer:
    return URLSafeSerializer(current_app.config["SECRET_KEY"], salt=salt)
