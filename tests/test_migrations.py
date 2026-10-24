"""The migrations must produce exactly the schema the models describe."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from flask_migrate import downgrade, upgrade
from sqlalchemy import create_engine, inspect

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
