"""Accounts and passwordless login (AUTH-01…05, NFA-09, E3)."""

import hashlib
import logging
import re
import secrets
import unicodedata
from datetime import datetime, timedelta

from flask import current_app
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.clock import get_clock
from app.extensions import db
from app.i18n import t
from app.models import AllowedEmail, LoginToken, User
from app.models.user import DISPLAY_NAME_MAX_LENGTH, EMAIL_MAX_LENGTH
from app.services import mail

log = logging.getLogger(__name__)

RATE_LIMIT_WINDOW = timedelta(hours=1)
# Deliberately loose: the only real check is whether the login link arrives.
_EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_TOKEN_SALT = "login-token"


class InvalidInput(ValueError):
    """Carries the translation key and parameters of the message to show."""

    def __init__(self, message_key: str, **params: object) -> None:
        super().__init__(message_key)
        self.message_key = message_key
        self.params = params

    def message(self) -> str:
        return t(self.message_key, **self.params)


def normalize_email(raw: str) -> str:
    email = raw.strip().lower()
    if len(email) > EMAIL_MAX_LENGTH or not _EMAIL_PATTERN.fullmatch(email):
        raise InvalidInput("auth.email_invalid")
    return email


def normalize_display_name(raw: str) -> str:
    name = " ".join(raw.split())
    if not name:
        raise InvalidInput("account.name_required")
    if len(name) > DISPLAY_NAME_MAX_LENGTH:
        raise InvalidInput("account.name_too_long", max=DISPLAY_NAME_MAX_LENGTH)
    if any(unicodedata.category(char) == "Cc" for char in name):
        raise InvalidInput("account.name_invalid")
    return name


def allow_email(raw: str) -> bool:
    """Adds an address to the allowlist. Returns False if it was already there."""
    email = normalize_email(raw)
    if db.session.get(AllowedEmail, email):
        return False
    db.session.add(AllowedEmail(email=email, added_at=get_clock().now()))
    db.session.commit()
    return True


def request_login(raw_email: str) -> None:
    """Sends a login link if the address may log in and is under the rate limit.

    Says nothing about which case applied, so the caller's response cannot reveal
    whether an account exists (E3).
    """
    email = normalize_email(raw_email)
    now = get_clock().now()
    if not _may_log_in(email) or _rate_limited(email, now):
        return
    nonce = secrets.token_urlsafe(32)
    db.session.add(
        LoginToken(
            email=email,
            nonce_hash=_hash(nonce),
            created_at=now,
            expires_at=now + current_app.config["LOGIN_TOKEN_LIFETIME"],
        )
    )
    db.session.commit()
    _send_login_mail(email, _serializer().dumps(nonce))


def redeem_login(link_token: str) -> User | None:
    """Uses up a login link and returns its account, creating it on first login."""
    nonce = _load_nonce(link_token)
    if nonce is None:
        return None
    now = get_clock().now()
    email = _consume(nonce, now)
    if email is None:
        return None
    user = _account_for(email, now)
    if user is not None and user.email_verified_at is None:
        user.email_verified_at = now  # AUTH-03
    # Commit even without a user, so the link stays used up.
    db.session.commit()
    return user


def set_display_name(user: User, raw: str) -> None:
    user.display_name = normalize_display_name(raw)
    db.session.commit()


def token_minutes() -> int:
    return int(current_app.config["LOGIN_TOKEN_LIFETIME"].total_seconds() // 60)


def login_link(link_token: str) -> str:
    return f"{current_app.config['BASE_URL']}/login/{link_token}"


def _may_log_in(email: str) -> bool:
    return _active_user(email) is not None or db.session.get(AllowedEmail, email) is not None


def _active_user(email: str) -> User | None:
    return db.session.scalar(select(User).where(User.email == email, User.deleted_at.is_(None)))


def _rate_limited(email: str, now: datetime) -> bool:
    recent = db.session.scalar(
        select(func.count())
        .select_from(LoginToken)
        .where(LoginToken.email == email, LoginToken.created_at > now - RATE_LIMIT_WINDOW)
    )
    return (recent or 0) >= current_app.config["LOGIN_MAILS_PER_HOUR"]


def _consume(nonce: str, now: datetime) -> str | None:
    """Marks the token used. The conditional UPDATE lets only one of two racing requests win."""
    nonce_hash = _hash(nonce)
    result = db.session.execute(
        update(LoginToken)
        .where(
            LoginToken.nonce_hash == nonce_hash,
            LoginToken.used_at.is_(None),
            LoginToken.expires_at > now,
        )
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.session.rollback()
        return None
    return db.session.scalar(select(LoginToken.email).where(LoginToken.nonce_hash == nonce_hash))


def _account_for(email: str, now: datetime) -> User | None:
    """The existing account, or a new one if the address is on the allowlist (E3)."""
    user = _active_user(email)
    if user is not None or db.session.get(AllowedEmail, email) is None:
        return user
    try:
        with db.session.begin_nested():
            user = User(email=email, created_at=now)
            db.session.add(user)
    except IntegrityError:
        # A parallel login created the account first (AUTH-01: one account per address).
        return _active_user(email)
    return user


def _send_login_mail(email: str, link_token: str) -> None:
    message = mail.Mail(
        to=email,
        subject=t("mail.login_subject"),
        body=t("mail.login_body", link=login_link(link_token), minutes=token_minutes()),
    )
    try:
        mail.send(message)
    except Exception:
        # The response must look the same as for unknown addresses (E3).
        log.exception("Could not send login mail")


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(current_app.config["SECRET_KEY"], salt=_TOKEN_SALT)


def _load_nonce(link_token: str) -> str | None:
    try:
        nonce = _serializer().loads(link_token)
    except BadSignature:
        return None
    return nonce if isinstance(nonce, str) else None


def _hash(nonce: str) -> str:
    return hashlib.sha256(nonce.encode()).hexdigest()
