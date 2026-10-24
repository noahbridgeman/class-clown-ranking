import sqlite3
from typing import Any

from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from sqlalchemy import MetaData, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase

# Explicit constraint names keep Alembic migrations stable on SQLite and Postgres.
# column_0_N_* covers all columns, so composite constraints sharing a first column
# get distinct names. Check constraints must be given an explicit name=.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
    """SQLite ignores foreign keys, and with them ON DELETE CASCADE, unless asked per connection."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


db = SQLAlchemy(model_class=Base)
# Batch mode lets Alembic alter tables on SQLite.
migrate = Migrate(render_as_batch=True)
csrf = CSRFProtect()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
# Flask-Login's default message is English; the login page explains itself.
login_manager.login_message = None
