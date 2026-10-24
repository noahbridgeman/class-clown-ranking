import re
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.extensions import db
from app.models import AllowedEmail, LoginToken, User
from app.services import auth
from app.services.mail import Mail
from tests.factories import allow, make_user

LINK = re.compile(r"http://localhost:5000/login/(\S+)")


def link_token(outbox: list[Mail]) -> str:
    return LINK.search(outbox[-1].body).group(1)


def token_count() -> int:
    return db.session.scalar(select(func.count()).select_from(LoginToken))


class TestNormalizeEmail:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("Anna@Example.ORG", "anna@example.org"), ("  bo@example.org \n", "bo@example.org")],
    )
    def test_strips_and_lowercases(self, raw, expected):
        assert auth.normalize_email(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            "anna",
            "anna@",
            "@example.org",
            "anna@example",
            "an na@example.org",
            "a@b@example.org",
            "anna@example.org\r\nBcc: x@example.org",
            "a" * 250 + "@x.de",
            "an\x00na@example.org",
            "anna@exam\u200bple.org",
            "anna\u202e@example.org",
        ],
    )
    def test_rejects_invalid(self, raw):
        with pytest.raises(auth.InvalidInput) as error:
            auth.normalize_email(raw)
        assert error.value.message_key == "auth.email_invalid"


class TestNormalizeDisplayName:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("  Anna  ", "Anna"),
            ("Anna   Lena", "Anna Lena"),
            ("Ä" * 40, "Ä" * 40),
            ("🤡", "🤡"),
            ("👨\u200d👩\u200d👧", "👨\u200d👩\u200d👧"),  # emoji ZWJ sequence
            ("José", "José"),  # combining accent
            ("李明", "李明"),
            ("O'Neill-Šimić", "O'Neill-Šimić"),
            ("שרה", "שרה"),
            ("A\u2028B", "A B"),  # line separators count as whitespace
        ],
    )
    def test_accepts_and_cleans_up(self, raw, expected):
        assert auth.normalize_display_name(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "key"),
        [
            ("", "account.name_required"),
            (" \t ", "account.name_required"),
            ("x" * 41, "account.name_too_long"),
            ("Anna\x00", "account.name_invalid"),
            ("An\x1bna", "account.name_invalid"),
            ("\u200b", "account.name_invalid"),  # zero-width space
            ("Anna\u202e", "account.name_invalid"),  # right-to-left override
            ("Anna\u2066x", "account.name_invalid"),  # bidi isolate
            ("An\u00adna", "account.name_invalid"),  # soft hyphen
            ("Anna\ue000", "account.name_invalid"),  # private use
            ("Anna\U000e0001", "account.name_invalid"),  # language tag
            ("\u3164", "account.name_required"),  # Hangul filler
            ("\u2800\u2800", "account.name_required"),  # braille blank
            ("\u0301", "account.name_required"),  # lone combining mark
            ("\u200d", "account.name_required"),  # lone joiner
        ],
    )
    def test_rejects_invalid(self, app, raw, key):
        with pytest.raises(auth.InvalidInput) as error:
            auth.normalize_display_name(raw)
        assert error.value.message_key == key
        assert error.value.message()

    def test_too_long_message_names_the_limit(self, app):
        with pytest.raises(auth.InvalidInput) as error:
            auth.normalize_display_name("x" * 41)
        assert "40" in error.value.message()


class TestAllowEmail:
    def test_adds_normalized_address(self, app):
        assert auth.allow_email(" Anna@Example.org ") is True
        assert db.session.get(AllowedEmail, "anna@example.org")

    def test_is_idempotent(self, app):
        auth.allow_email("anna@example.org")
        assert auth.allow_email("ANNA@example.org") is False
        assert db.session.scalar(select(func.count()).select_from(AllowedEmail)) == 1


class TestRequestLogin:
    def test_existing_account_gets_a_link(self, app, outbox):
        make_user("anna@example.org")
        auth.request_login("Anna@Example.org")
        assert [mail.to for mail in outbox] == ["anna@example.org"]
        assert "15 Minuten" in outbox[0].body
        assert LINK.search(outbox[0].body)

    def test_allowlisted_address_gets_a_link(self, app, outbox):
        allow("neu@example.org")
        auth.request_login("neu@example.org")
        assert [mail.to for mail in outbox] == ["neu@example.org"]

    def test_unknown_address_gets_nothing(self, app, outbox):
        auth.request_login("fremd@example.org")
        assert outbox == []
        assert token_count() == 0

    def test_deleted_account_gets_nothing(self, app, outbox, clock):
        user = make_user("weg@example.org")
        user.deleted_at = clock.now()
        db.session.commit()
        auth.request_login("weg@example.org")
        assert outbox == []

    def test_only_the_hash_of_the_nonce_is_stored(self, app, outbox):
        make_user("anna@example.org")
        auth.request_login("anna@example.org")
        token = db.session.scalar(select(LoginToken))
        assert len(token.nonce_hash) == 64
        assert token.nonce_hash not in outbox[0].body

    def test_token_expires_after_15_minutes(self, app, outbox, clock):
        make_user("anna@example.org")
        auth.request_login("anna@example.org")
        token = db.session.scalar(select(LoginToken))
        assert token.created_at == clock.now()
        assert token.expires_at == clock.now() + timedelta(minutes=15)

    def test_mail_failure_is_swallowed(self, app, monkeypatch, caplog):
        make_user("anna@example.org")

        def fail(_mail):
            raise OSError("SMTP down")

        monkeypatch.setattr(auth.mail, "send", fail)
        auth.request_login("anna@example.org")
        assert "Could not send login mail" in caplog.text

    def test_invalid_address_raises(self, app):
        with pytest.raises(auth.InvalidInput):
            auth.request_login("kein-at")


class TestRateLimit:
    def test_sixth_request_within_an_hour_sends_nothing(self, app, outbox, clock):
        make_user("anna@example.org")
        for _ in range(5):
            auth.request_login("anna@example.org")
            clock.advance(timedelta(minutes=1))
        auth.request_login("anna@example.org")
        assert len(outbox) == 5
        assert token_count() == 5

    def test_limit_holds_until_just_before_an_hour(self, app, outbox, clock):
        make_user("anna@example.org")
        for _ in range(5):
            auth.request_login("anna@example.org")
        clock.advance(timedelta(hours=1) - timedelta(microseconds=1))
        auth.request_login("anna@example.org")
        assert len(outbox) == 5

    def test_limit_frees_up_after_an_hour(self, app, outbox, clock):
        make_user("anna@example.org")
        for _ in range(5):
            auth.request_login("anna@example.org")
        clock.advance(timedelta(hours=1))
        auth.request_login("anna@example.org")
        assert len(outbox) == 6

    def test_limit_is_per_address(self, app, outbox):
        make_user("anna@example.org")
        make_user("bo@example.org")
        for _ in range(5):
            auth.request_login("anna@example.org")
        auth.request_login("bo@example.org")
        assert outbox[-1].to == "bo@example.org"

    def test_used_tokens_still_count(self, app, outbox):
        make_user("anna@example.org")
        for _ in range(5):
            auth.request_login("anna@example.org")
            assert auth.redeem_login(link_token(outbox))
        auth.request_login("anna@example.org")
        assert len(outbox) == 5


class TestRedeemLogin:
    def test_logs_in_existing_account(self, app, outbox):
        user = make_user("anna@example.org")
        auth.request_login("anna@example.org")
        assert auth.redeem_login(link_token(outbox)) == user

    def test_first_login_creates_verified_account(self, app, outbox, clock):
        allow("neu@example.org")
        auth.request_login("neu@example.org")
        clock.advance(timedelta(minutes=3))
        user = auth.redeem_login(link_token(outbox))
        assert user.email == "neu@example.org"
        assert user.display_name is None
        assert user.email_verified_at == clock.now()
        assert user.created_at == clock.now()

    def test_verification_time_is_kept_on_later_logins(self, app, outbox, clock):
        allow("neu@example.org")
        auth.request_login("neu@example.org")
        first = auth.redeem_login(link_token(outbox)).email_verified_at
        clock.advance(timedelta(days=1))
        auth.request_login("neu@example.org")
        assert auth.redeem_login(link_token(outbox)).email_verified_at == first

    def test_one_account_per_address(self, app, outbox):
        allow("neu@example.org")
        auth.request_login("neu@example.org")
        auth.request_login("neu@example.org")
        first, second = (LINK.search(mail.body).group(1) for mail in outbox)
        assert auth.redeem_login(first) == auth.redeem_login(second)
        assert db.session.scalar(select(func.count()).select_from(User)) == 1

    def test_link_works_only_once(self, app, outbox):
        make_user("anna@example.org")
        auth.request_login("anna@example.org")
        token = link_token(outbox)
        assert auth.redeem_login(token)
        assert auth.redeem_login(token) is None

    def test_link_is_valid_just_before_expiry(self, app, outbox, clock):
        make_user("anna@example.org")
        auth.request_login("anna@example.org")
        clock.advance(timedelta(minutes=15) - timedelta(microseconds=1))
        assert auth.redeem_login(link_token(outbox))

    def test_link_expires_after_15_minutes(self, app, outbox, clock):
        make_user("anna@example.org")
        auth.request_login("anna@example.org")
        clock.advance(timedelta(minutes=15))
        assert auth.redeem_login(link_token(outbox)) is None

    def test_older_links_stay_valid_when_a_new_one_is_requested(self, app, outbox):
        make_user("anna@example.org")
        auth.request_login("anna@example.org")
        first = link_token(outbox)
        auth.request_login("anna@example.org")
        assert auth.redeem_login(first)

    @pytest.mark.parametrize("token", ["", "garbage", "eyJub25jZSI6MX0.abc"])
    def test_rejects_garbage(self, app, token):
        assert auth.redeem_login(token) is None

    def test_rejects_tampered_signature(self, app, outbox):
        make_user("anna@example.org")
        auth.request_login("anna@example.org")
        token = link_token(outbox)
        payload, signature = token.rsplit(".", 1)
        # The last base64 character may carry unused bits, so change the first one.
        tampered = f"{payload}.{'B' if signature[0] == 'A' else 'A'}{signature[1:]}"
        assert auth.redeem_login(tampered) is None
        assert auth.redeem_login(token)

    def test_rejects_token_signed_with_other_key(self, app, outbox):
        from itsdangerous import URLSafeSerializer

        make_user("anna@example.org")
        auth.request_login("anna@example.org")
        nonce = auth._load_nonce(link_token(outbox))
        forged = URLSafeSerializer("other-secret", salt="login-token").dumps(nonce)
        assert auth.redeem_login(forged) is None

    def test_rejects_signed_non_string_payload(self, app):
        assert auth.redeem_login(auth._serializer().dumps(["not", "a", "nonce"])) is None

    def test_failed_redemption_leaves_pending_changes_alone(self, app):
        # From M3 on, invitation acceptance may run in the same transaction.
        allowed = AllowedEmail(email="pending@example.org", added_at=auth.get_clock().now())
        db.session.add(allowed)
        db.session.flush()
        assert auth.redeem_login(auth._serializer().dumps("unknown-nonce")) is None
        assert allowed in db.session
        db.session.commit()
        assert db.session.get(AllowedEmail, "pending@example.org")

    def test_deleted_account_cannot_log_in(self, app, outbox, clock):
        user = make_user("anna@example.org")
        auth.request_login("anna@example.org")
        user.deleted_at = clock.now()
        db.session.commit()
        assert auth.redeem_login(link_token(outbox)) is None

    def test_removed_from_allowlist_before_first_login(self, app, outbox):
        allow("neu@example.org")
        auth.request_login("neu@example.org")
        db.session.delete(db.session.get(AllowedEmail, "neu@example.org"))
        db.session.commit()
        token = link_token(outbox)
        assert auth.redeem_login(token) is None
        assert db.session.scalar(select(LoginToken.used_at)) is not None
        assert db.session.scalar(select(func.count()).select_from(User)) == 0

    def test_concurrent_account_creation_falls_back_to_existing(self, app, outbox, monkeypatch):
        allow("neu@example.org")
        auth.request_login("neu@example.org")
        token = link_token(outbox)
        # Simulate a parallel request that created the account after our lookup.
        original = auth._active_user
        calls = iter([None])

        def racing_lookup(email):
            if next(calls, "done") is None:
                make_user(email, display_name=None)
                return None
            return original(email)

        monkeypatch.setattr(auth, "_active_user", racing_lookup)
        user = auth.redeem_login(token)
        assert user is not None
        assert db.session.scalar(select(func.count()).select_from(User)) == 1


class TestSetDisplayName:
    def test_sets_cleaned_name(self, app):
        user = make_user(display_name=None)
        auth.set_display_name(user, "  Anna   Lena ")
        db.session.expire_all()
        assert db.session.get(User, user.id).display_name == "Anna Lena"

    def test_invalid_name_keeps_old_one(self, app):
        user = make_user(display_name="Anna")
        with pytest.raises(auth.InvalidInput):
            auth.set_display_name(user, "   ")
        db.session.expire_all()
        assert db.session.get(User, user.id).display_name == "Anna"
