import io
from typing import ClassVar

import pytest

from app.services import mail
from app.services.mail import ConsoleBackend, Mail, MemoryBackend, SmtpBackend

MESSAGE = Mail(to="anna@example.org", subject="Betreff", body="Hallo Anna")
SMTP_CONFIG = {
    "MAIL_HOST": "smtp.example.org",
    "MAIL_PORT": 587,
    "MAIL_USERNAME": "user",
    "MAIL_PASSWORD": "pw",
    "MAIL_STARTTLS": True,
    "MAIL_FROM": "ranking@example.org",
}


class FakeSmtp:
    instances: ClassVar[list["FakeSmtp"]] = []

    def __init__(self, host, port, timeout, context=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.calls: list[str] = []
        self.sent = []
        FakeSmtp.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.calls.append("quit")

    def starttls(self, context):
        self.calls.append("starttls")

    def login(self, username, password):
        self.calls.append(f"login:{username}:{password}")

    def send_message(self, message):
        self.calls.append("send")
        self.sent.append(message)


@pytest.fixture
def fake_smtp(monkeypatch):
    FakeSmtp.instances = []
    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSmtp)
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", FakeSmtp)
    return FakeSmtp.instances


def test_memory_backend_collects_mails():
    backend = MemoryBackend()
    backend.send(MESSAGE)
    assert backend.outbox == [MESSAGE]


def test_console_backend_prints_mail():
    stream = io.StringIO()
    ConsoleBackend(stream).send(MESSAGE)
    assert "anna@example.org" in stream.getvalue()
    assert "Hallo Anna" in stream.getvalue()


def test_smtp_backend_uses_starttls_and_login(fake_smtp):
    SmtpBackend(SMTP_CONFIG).send(MESSAGE)
    (smtp,) = fake_smtp
    assert (smtp.host, smtp.port, smtp.timeout) == ("smtp.example.org", 587, 10)
    assert smtp.calls == ["starttls", "login:user:pw", "send", "quit"]
    message = smtp.sent[0]
    assert message["From"] == "ranking@example.org"
    assert message["To"] == "anna@example.org"
    assert message["Subject"] == "Betreff"
    assert message.get_content().strip() == "Hallo Anna"


def test_smtp_backend_without_credentials_skips_login(fake_smtp):
    SmtpBackend({**SMTP_CONFIG, "MAIL_USERNAME": None, "MAIL_STARTTLS": False}).send(MESSAGE)
    assert fake_smtp[0].calls == ["send", "quit"]


def test_smtp_backend_uses_implicit_tls_on_port_465(fake_smtp):
    SmtpBackend({**SMTP_CONFIG, "MAIL_PORT": 465}).send(MESSAGE)
    assert "starttls" not in fake_smtp[0].calls


def test_umlauts_survive_encoding(fake_smtp):
    SmtpBackend(SMTP_CONFIG).send(Mail(to="a@example.org", subject="Spaßvogel", body="Grüße"))
    message = fake_smtp[0].sent[0]
    assert message["Subject"] == "Spaßvogel"
    assert message.get_content().strip() == "Grüße"


def test_app_uses_memory_backend_in_tests(app):
    assert isinstance(app.extensions["mail"], MemoryBackend)
