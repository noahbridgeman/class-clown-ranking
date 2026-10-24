"""The migrations must produce exactly the schema the models describe."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from flask_migrate import downgrade, upgrade
from sqlalchemy import create_engine, inspect, text

from app import create_app
from app.config import TestConfig
from app.extensions import db


def _app(tmp_path):
    class FileDb(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'migrated.db'}"

    return create_app(FileDb)


def test_upgrade_matches_models(tmp_path):
    app = _app(tmp_path)
    with app.app_context():
        upgrade()
        with db.engine.connect() as connection:
            diff = compare_metadata(MigrationContext.configure(connection), db.metadata)
        db.engine.dispose()
    assert diff == []


def test_downgrade_removes_everything(tmp_path):
    app = _app(tmp_path)
    with app.app_context():
        upgrade()
        downgrade(revision="base")
        db.engine.dispose()
    engine = create_engine(f"sqlite:///{tmp_path / 'migrated.db'}")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    engine.dispose()


def test_foreign_keys_are_back_on_after_migrating(tmp_path):
    app = _app(tmp_path)
    with app.app_context():
        upgrade()
        assert db.session.execute(text("PRAGMA foreign_keys")).scalar() == 1
        db.session.remove()
        db.engine.dispose()


def test_rebuilding_groups_keeps_dependent_rows(tmp_path):
    """Batch mode recreates groups; with foreign keys on, that would cascade-delete."""
    app = _app(tmp_path)
    with app.app_context():
        upgrade(revision="5cc73ad34f8c")
        with db.engine.begin() as connection:
            for statement in SEED:
                connection.execute(text(statement))
        upgrade()
        with db.engine.connect() as connection:
            memberships = connection.execute(text("SELECT count(*) FROM memberships")).scalar()
            invitations = connection.execute(text("SELECT count(*) FROM invitations")).scalar()
            creator = connection.execute(text("SELECT created_by_user_id FROM groups")).scalar()
        db.engine.dispose()
    assert (memberships, invitations, creator) == (1, 1, 1)


NOW = "'2026-10-24 12:00:00'"
SEED = [
    f"INSERT INTO users (id, email, session_version, created_at) VALUES (1, 'a@x.org', 1, {NOW})",
    "INSERT INTO groups (id, name, admin_user_id, cadence, is_anonymous, timezone, k, d, "
    f"created_at) VALUES (1, 'Runde', 1, 'weekly', 1, 'Europe/Berlin', 0.5, 0.95, {NOW})",
    "INSERT INTO memberships (group_id, user_id, first_joined_at, joined_at, color_index) "
    f"VALUES (1, 1, {NOW}, {NOW}, 0)",
    "INSERT INTO invitations (group_id, email, invited_by_user_id, nonce_hash, created_at, "
    f"last_sent_at, expires_at, send_count) VALUES (1, 'b@x.org', 1, 'h', {NOW}, {NOW}, {NOW}, 1)",
]
