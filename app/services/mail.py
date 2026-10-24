"""Outgoing e-mail. Only used for login links and, from M3 on, invitations."""

import logging
import smtplib
import ssl
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid, parseaddr
from typing import Any, Protocol, TextIO

from flask import Flask, current_app

log = logging.getLogger(__name__)

SMTP_TIMEOUT_SECONDS = 10
IMPLICIT_TLS_PORT = 465


@dataclass(frozen=True)
class Mail:
    to: str
    subject: str
    body: str


class MailBackend(Protocol):
    def send(self, mail: Mail) -> None: ...


class SmtpBackend:
    def __init__(self, config: Mapping[str, Any], now: Callable[[], datetime]) -> None:
        self._host: str = config["MAIL_HOST"]
        self._port = int(config["MAIL_PORT"])
        self._username: str | None = config["MAIL_USERNAME"]
        self._password: str | None = config["MAIL_PASSWORD"]
        self._starttls = bool(config["MAIL_STARTTLS"])
        self._sender: str = config["MAIL_FROM"]
        self._now = now

    @property
    def encrypted(self) -> bool:
        return self._port == IMPLICIT_TLS_PORT or self._starttls

    def send(self, mail: Mail) -> None:
        with self._connect() as smtp:
            if self._username:
                smtp.login(self._username, self._password or "")
            smtp.send_message(self._message(mail))

    def _message(self, mail: Mail) -> EmailMessage:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = mail.to
        message["Subject"] = mail.subject
        # Spam filters penalize mails without these.
        message["Date"] = format_datetime(self._now())
        message["Message-ID"] = make_msgid(domain=_domain(self._sender))
        message.set_content(mail.body)
        return message

    def _connect(self) -> smtplib.SMTP:
        context = ssl.create_default_context()
        if self._port == IMPLICIT_TLS_PORT:
            return smtplib.SMTP_SSL(
                self._host, self._port, timeout=SMTP_TIMEOUT_SECONDS, context=context
            )
        smtp = smtplib.SMTP(self._host, self._port, timeout=SMTP_TIMEOUT_SECONDS)
        if self._starttls:
            try:
                smtp.starttls(context=context)
            except Exception:
                smtp.close()
                raise
        return smtp


class ConsoleBackend:
    """Development: prints mails instead of sending them, so login links can be clicked."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream

    def send(self, mail: Mail) -> None:
        stream = self._stream or sys.stderr
        print(
            f"--- To: {mail.to}\nSubject: {mail.subject}\n\n{mail.body}\n---",
            file=stream,
            flush=True,
        )


class MemoryBackend:
    """Tests: collects mails in outbox."""

    def __init__(self) -> None:
        self.outbox: list[Mail] = []

    def send(self, mail: Mail) -> None:
        self.outbox.append(mail)


def init_app(app: Flask) -> None:
    app.extensions["mail"] = backend_from_config(app.config, app.extensions["clock"].now)


def backend_from_config(config: Mapping[str, Any], now: Callable[[], datetime]) -> MailBackend:
    name = config["MAIL_BACKEND"]
    if name == "smtp":
        return _smtp_backend(config, now)
    if name == "console":
        return ConsoleBackend()
    if name == "memory":
        return MemoryBackend()
    raise RuntimeError(f"Unknown MAIL_BACKEND {name!r}, expected smtp, console or memory")


def send(mail: Mail) -> None:
    current_app.extensions["mail"].send(mail)


def try_send(mail: Mail) -> bool:
    """Sends a mail after the transaction has been committed; a failure is only logged."""
    try:
        send(mail)
    except Exception:
        log.exception("Could not send mail with subject %r", mail.subject)
        return False
    return True


def _smtp_backend(config: Mapping[str, Any], now: Callable[[], datetime]) -> SmtpBackend:
    missing = [key for key in ("MAIL_HOST", "MAIL_FROM") if not config[key]]
    if missing:
        raise RuntimeError(f"{', '.join(missing)} must be set for MAIL_BACKEND=smtp")
    if not _domain(config["MAIL_FROM"]):
        raise RuntimeError("MAIL_FROM must be an e-mail address")
    backend = SmtpBackend(config, now)
    if config["MAIL_USERNAME"] and not backend.encrypted:
        raise RuntimeError(
            f"SMTP login without encryption: use port {IMPLICIT_TLS_PORT} or MAIL_STARTTLS=true"
        )
    return backend


def _domain(address: str) -> str:
    """The domain of an address such as "Name <user@example.org>", or "" without one."""
    _local, at, domain = parseaddr(address)[1].rpartition("@")
    return domain if at else ""
