"""Outgoing e-mail. Only used for login links and, from M3 on, invitations."""

import smtplib
import ssl
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any, Protocol, TextIO

from flask import Flask, current_app

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
    def __init__(self, config: Mapping[str, Any]) -> None:
        self._host: str = config["MAIL_HOST"]
        self._port = int(config["MAIL_PORT"])
        self._username: str | None = config["MAIL_USERNAME"]
        self._password: str | None = config["MAIL_PASSWORD"]
        self._starttls = bool(config["MAIL_STARTTLS"])
        self._sender: str = config["MAIL_FROM"]

    def send(self, mail: Mail) -> None:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = mail.to
        message["Subject"] = mail.subject
        message.set_content(mail.body)
        with self._connect() as smtp:
            if self._username:
                smtp.login(self._username, self._password or "")
            smtp.send_message(message)

    def _connect(self) -> smtplib.SMTP:
        context = ssl.create_default_context()
        if self._port == IMPLICIT_TLS_PORT:
            return smtplib.SMTP_SSL(
                self._host, self._port, timeout=SMTP_TIMEOUT_SECONDS, context=context
            )
        smtp = smtplib.SMTP(self._host, self._port, timeout=SMTP_TIMEOUT_SECONDS)
        if self._starttls:
            smtp.starttls(context=context)
        return smtp


class ConsoleBackend:
    """Development: prints mails instead of sending them, so login links can be clicked."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream

    def send(self, mail: Mail) -> None:
        stream = self._stream or sys.stderr
        print(f"--- Mail an {mail.to}: {mail.subject}\n{mail.body}\n---", file=stream, flush=True)


class MemoryBackend:
    """Tests: collects mails in outbox."""

    def __init__(self) -> None:
        self.outbox: list[Mail] = []

    def send(self, mail: Mail) -> None:
        self.outbox.append(mail)


def init_app(app: Flask) -> None:
    app.extensions["mail"] = backend_from_config(app.config)


def backend_from_config(config: Mapping[str, Any]) -> MailBackend:
    name = config["MAIL_BACKEND"]
    if name == "smtp":
        missing = [key for key in ("MAIL_HOST", "MAIL_FROM") if not config[key]]
        if missing:
            raise RuntimeError(f"{', '.join(missing)} must be set for MAIL_BACKEND=smtp")
        return SmtpBackend(config)
    if name == "console":
        return ConsoleBackend()
    if name == "memory":
        return MemoryBackend()
    raise RuntimeError(f"Unknown MAIL_BACKEND {name!r}, expected smtp, console or memory")


def send(mail: Mail) -> None:
    current_app.extensions["mail"].send(mail)
