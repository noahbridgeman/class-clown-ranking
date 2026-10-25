"""Web push (NOT-01…04, NFA-02, A24): subscriptions, preferences and delivery.

What to send and to whom is decided in app.services.notifications; this module only
filters by the recipients' preferences and hands the message to every device they
subscribed. Delivery runs after the deciding transaction has been committed.
"""

import base64
import json
import logging
import sys
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any, Protocol, TextIO
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from flask import Flask, current_app
from sqlalchemy import delete, select

from app.clock import get_clock
from app.extensions import db
from app.models import NotificationKind, NotificationPreference, PushSubscription, User
from app.models.push import ENDPOINT_MAX_LENGTH, KEY_MAX_LENGTH
from app.services.errors import InvalidInput

log = logging.getLogger(__name__)

# The server only posts to the big browsers' push services, never to an address a
# client made up (SSRF). Hosts match exactly or as a subdomain.
PUSH_SERVICE_HOSTS = (
    "fcm.googleapis.com",
    "android.googleapis.com",
    "push.services.mozilla.com",
    "push.apple.com",
    "notify.windows.com",
)
GONE_STATUSES = {404, 410}  # the subscription no longer exists


@dataclass(frozen=True)
class Push:
    title: str
    body: str
    url: str  # path inside the app that a tap opens
    tag: str  # a newer push with the same tag replaces the older one


@dataclass(frozen=True)
class Delivery:
    user_id: int
    group_id: int
    kind: NotificationKind
    push: Push


@dataclass(frozen=True)
class Target:
    endpoint: str
    p256dh: str
    auth: str


class PushGone(Exception):
    """The push service no longer knows the subscription."""


class PushBackend(Protocol):
    def send(self, target: Target, push: Push) -> None: ...


class WebPushBackend:
    def __init__(self, config: Mapping[str, Any]) -> None:
        self._private_key: str = config["VAPID_PRIVATE_KEY"]
        self._subject: str = config["VAPID_SUBJECT"]
        self._timeout = float(config["PUSH_TIMEOUT_SECONDS"])
        self._ttl = int(config["PUSH_TTL_SECONDS"])

    def send(self, target: Target, push: Push) -> None:
        from pywebpush import WebPushException, webpush

        try:
            webpush(
                subscription_info={
                    "endpoint": target.endpoint,
                    "keys": {"p256dh": target.p256dh, "auth": target.auth},
                },
                data=payload(push),
                vapid_private_key=self._private_key,
                vapid_claims={"sub": self._subject},
                timeout=self._timeout,
                ttl=self._ttl,
            )
        except WebPushException as error:
            if error.response is not None and error.response.status_code in GONE_STATUSES:
                raise PushGone(target.endpoint) from error
            raise


class ConsoleBackend:
    """Development: prints pushes instead of sending them."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream

    def send(self, target: Target, push: Push) -> None:
        print(
            f"--- Push to {target.endpoint[:48]}…\n{payload(push)}\n---",
            file=self._stream or sys.stderr,
        )


class MemoryBackend:
    """Tests: collects (endpoint, push) in outbox; endpoints in gone answer 410."""

    def __init__(self) -> None:
        self.outbox: list[tuple[str, Push]] = []
        self.gone: set[str] = set()

    def send(self, target: Target, push: Push) -> None:
        if target.endpoint in self.gone:
            raise PushGone(target.endpoint)
        self.outbox.append((target.endpoint, push))


def init_app(app: Flask) -> None:
    app.extensions["push"] = backend_from_config(app.config)


def backend_from_config(config: Mapping[str, Any]) -> PushBackend:
    name = config["PUSH_BACKEND"]
    if name == "webpush":
        missing = [
            k for k in ("VAPID_PRIVATE_KEY", "VAPID_PUBLIC_KEY", "VAPID_SUBJECT") if not config[k]
        ]
        if missing:
            raise RuntimeError(f"{', '.join(missing)} must be set for PUSH_BACKEND=webpush")
        if urlsplit(config["VAPID_SUBJECT"]).scheme not in {"mailto", "https"}:
            raise RuntimeError("VAPID_SUBJECT must be a mailto: or https: address")
        return WebPushBackend(config)
    if name == "console":
        return ConsoleBackend()
    if name == "memory":
        return MemoryBackend()
    raise RuntimeError(f"Unknown PUSH_BACKEND {name!r}, expected webpush, console or memory")


def payload(push: Push) -> str:
    """What sw.js receives."""
    return json.dumps(asdict(push), ensure_ascii=False)


def public_key() -> str | None:
    """The application server key the browser subscribes with; None without push."""
    return current_app.config["VAPID_PUBLIC_KEY"]


# Delivery


def deliver(deliveries: Iterable[Delivery]) -> int:
    """Sends after the commit; returns how many devices accepted a push.

    Occasions switched off for the group are skipped (NOT-02). A failure is only logged,
    so a broken push service never undoes or repeats what was decided (NOT-03).
    """
    deliveries = list(deliveries)
    if not deliveries:
        return 0
    user_ids = {d.user_id for d in deliveries}
    off = _switched_off(user_ids)
    targets = _targets(user_ids)
    backend: PushBackend = current_app.extensions["push"]
    sent, gone = 0, set()
    for delivery in deliveries:
        if (delivery.user_id, delivery.group_id, delivery.kind) in off:
            continue
        for subscription_id, target in targets.get(delivery.user_id, []):
            if subscription_id in gone:
                continue
            try:
                backend.send(target, delivery.push)
            except PushGone:
                gone.add(subscription_id)
            except Exception:
                log.exception("Could not send push %s to %s", delivery.kind, target.endpoint[:48])
            else:
                sent += 1
    if gone:
        db.session.execute(delete(PushSubscription).where(PushSubscription.id.in_(gone)))
        db.session.commit()
    return sent


def _switched_off(user_ids: set[int]) -> set[tuple[int, int, NotificationKind]]:
    rows = db.session.execute(
        select(
            NotificationPreference.user_id,
            NotificationPreference.group_id,
            NotificationPreference.kind,
        ).where(
            NotificationPreference.user_id.in_(user_ids),
            NotificationPreference.enabled.is_(False),
        )
    )
    return {(u, g, k) for u, g, k in rows}


def _targets(user_ids: set[int]) -> dict[int, list[tuple[int, Target]]]:
    rows = db.session.scalars(
        select(PushSubscription).where(PushSubscription.user_id.in_(user_ids))
    )
    targets: dict[int, list[tuple[int, Target]]] = {}
    for s in rows:
        targets.setdefault(s.user_id, []).append((s.id, Target(s.endpoint, s.p256dh, s.auth)))
    return targets


# Subscriptions


def subscribe(user: User, endpoint: str, p256dh: str, auth: str) -> None:
    """Stores this device's subscription (NOT-01: only after the user switched push on).

    An endpoint known for another account moves to this one, as the device changed
    hands. Beyond the limit per account, the oldest subscriptions go.
    """
    endpoint, p256dh, auth = endpoint.strip(), p256dh.strip(), auth.strip()
    _check(endpoint, p256dh, auth)
    existing = db.session.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == endpoint)
    )
    now = get_clock().now()
    if existing is None:
        db.session.add(
            PushSubscription(
                user_id=user.id, endpoint=endpoint, p256dh=p256dh, auth=auth, created_at=now
            )
        )
    else:
        existing.user_id, existing.p256dh, existing.auth, existing.created_at = (
            user.id,
            p256dh,
            auth,
            now,
        )
    db.session.flush()
    limit = current_app.config["PUSH_SUBSCRIPTIONS_PER_USER"]
    surplus = db.session.scalars(
        select(PushSubscription.id)
        .where(PushSubscription.user_id == user.id)
        .order_by(PushSubscription.created_at.desc(), PushSubscription.id.desc())
        .offset(limit)
    ).all()
    if surplus:
        db.session.execute(delete(PushSubscription).where(PushSubscription.id.in_(surplus)))
    db.session.commit()


def unsubscribe(user: User, endpoint: str | None) -> None:
    """Removes this device's subscription, e.g. on logout. Unknown endpoints are ignored."""
    if not endpoint:
        return
    db.session.execute(
        delete(PushSubscription).where(
            PushSubscription.user_id == user.id, PushSubscription.endpoint == endpoint.strip()
        )
    )
    db.session.commit()


def _check(endpoint: str, p256dh: str, auth: str) -> None:
    parts = urlsplit(endpoint)
    host = (parts.hostname or "").lower()
    allowed = any(host == h or host.endswith(f".{h}") for h in PUSH_SERVICE_HOSTS)
    if parts.scheme != "https" or not allowed or len(endpoint) > ENDPOINT_MAX_LENGTH:
        raise InvalidInput("push.invalid_subscription")
    for key in (p256dh, auth):
        if not key or len(key) > KEY_MAX_LENGTH or not _is_base64url(key):
            raise InvalidInput("push.invalid_subscription")


def _is_base64url(value: str) -> bool:
    try:
        base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except ValueError:
        return False
    return all(c.isalnum() or c in "-_=" for c in value)


# Preferences (NOT-02)


def preferences(user_id: int, group_id: int) -> dict[NotificationKind, bool]:
    stored = dict(
        db.session.execute(
            select(NotificationPreference.kind, NotificationPreference.enabled).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.group_id == group_id,
            )
        ).all()
    )
    return {kind: stored.get(kind, True) for kind in NotificationKind}


def set_preferences(user: User, group_id: int, enabled: set[NotificationKind]) -> None:
    """Stores every occasion as on or off for this group. The caller checks membership."""
    db.session.execute(
        delete(NotificationPreference).where(
            NotificationPreference.user_id == user.id,
            NotificationPreference.group_id == group_id,
        )
    )
    db.session.add_all(
        NotificationPreference(
            user_id=user.id, group_id=group_id, kind=kind, enabled=kind in enabled
        )
        for kind in NotificationKind
    )
    db.session.commit()


# Keys


def generate_vapid_keys() -> tuple[str, str]:
    """(private, public), both base64url: the raw private number and the uncompressed
    public point, as pywebpush and the browser's applicationServerKey expect them."""
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_numbers().private_value.to_bytes(32, "big")
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return _b64url(private), _b64url(public)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
