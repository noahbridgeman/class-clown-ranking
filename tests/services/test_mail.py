import io
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import ClassVar

import pytest

from app.services import mail
from app.services.mail import ConsoleBackend, Mail, MemoryBackend, SmtpBackend

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
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
    fail_starttls: ClassVar[bool] = False

    def __init__(self, host, port, timeout, context=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.calls: list[str] = []
        self.sent = []
        self.fail_starttls = FakeSmtp.fail_starttls
        FakeSmtp.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.calls.append("quit")

    def starttls(self, context):
        self.calls.append("starttls")
        if self.fail_starttls:
            raise OSError("TLS handshake failed")

    def close(self):
        self.calls.append("close")

    def login(self, username, password):
        self.calls.append(f"login:{username}:{password}")

    def send_message(self, message):
        self.calls.append("send")
        self.sent.append(message)


@pytest.fixture
def fake_smtp(monkeypatch):
    FakeSmtp.instances = []
    FakeSmtp.fail_starttls = False
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
    SmtpBackend(SMTP_CONFIG, lambda: NOW).send(MESSAGE)
    (smtp,) = fake_smtp
    assert (smtp.host, smtp.port, smtp.timeout) == ("smtp.example.org", 587, 10)
    assert smtp.calls == ["starttls", "login:user:pw", "send", "quit"]
    message = smtp.sent[0]
    assert message["From"] == "ranking@example.org"
    assert message["To"] == "anna@example.org"
    assert message["Subject"] == "Betreff"
    assert message.get_content().strip() == "Hallo Anna"


def test_smtp_message_has_date_and_message_id(fake_smtp):
    SmtpBackend(SMTP_CONFIG, lambda: NOW).send(MESSAGE)
    message = fake_smtp[0].sent[0]
    assert parsedate_to_datetime(message["Date"]) == NOW
    assert message["Message-ID"].endswith("@example.org>")


def test_failed_starttls_closes_the_connection(fake_smtp):
    FakeSmtp.fail_starttls = True
    with pytest.raises(OSError, match="TLS"):
        SmtpBackend(SMTP_CONFIG, lambda: NOW).send(MESSAGE)
    assert fake_smtp[0].calls == ["starttls", "close"]


class TestBackendFromConfig:
    def config(self, **overrides):
        return {"MAIL_BACKEND": "smtp", **SMTP_CONFIG, **overrides}

    def test_builds_smtp_backend(self):
        assert isinstance(mail.backend_from_config(self.config(), lambda: NOW), SmtpBackend)

    def test_rejects_login_without_encryption(self):
        with pytest.raises(RuntimeError, match="without encryption"):
            mail.backend_from_config(self.config(MAIL_STARTTLS=False), lambda: NOW)

    def test_allows_implicit_tls_without_starttls(self):
        config = self.config(MAIL_STARTTLS=False, MAIL_PORT=465)
        assert mail.backend_from_config(config, lambda: NOW)

    def test_allows_unencrypted_relay_without_login(self):
        config = self.config(MAIL_STARTTLS=False, MAIL_USERNAME=None)
        assert mail.backend_from_config(config, lambda: NOW)

    @pytest.mark.parametrize("sender", ["ranking", "Ranking <ranking>"])
    def test_rejects_sender_without_domain(self, sender):
        with pytest.raises(RuntimeError, match="MAIL_FROM"):
            mail.backend_from_config(self.config(MAIL_FROM=sender), lambda: NOW)

    def test_sender_with_display_name_is_fine(self, fake_smtp):
        config = self.config(MAIL_FROM="Spaßvogel-Ranking <ranking@example.org>")
        mail.backend_from_config(config, lambda: NOW).send(MESSAGE)
        assert fake_smtp[0].sent[0]["Message-ID"].endswith("@example.org>")


def test_smtp_backend_without_credentials_skips_login(fake_smtp):
    SmtpBackend({**SMTP_CONFIG, "MAIL_USERNAME": None, "MAIL_STARTTLS": False}, lambda: NOW).send(
        MESSAGE
    )
    assert fake_smtp[0].calls == ["send", "quit"]


def test_smtp_backend_uses_implicit_tls_on_port_465(fake_smtp):
    SmtpBackend({**SMTP_CONFIG, "MAIL_PORT": 465}, lambda: NOW).send(MESSAGE)
    assert "starttls" not in fake_smtp[0].calls


def test_umlauts_survive_encoding(fake_smtp):
    SmtpBackend(SMTP_CONFIG, lambda: NOW).send(
        Mail(to="a@example.org", subject="Spaßvogel", body="Grüße")
    )
    message = fake_smtp[0].sent[0]
    assert message["Subject"] == "Spaßvogel"
    assert message.get_content().strip() == "Grüße"


def test_app_uses_memory_backend_in_tests(app):
    assert isinstance(app.extensions["mail"], MemoryBackend)
