from sqlalchemy import (
    Column,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Table,
    UniqueConstraint,
)
from sqlalchemy.schema import CreateIndex, CreateTable

from app.extensions import NAMING_CONVENTION


def _composite_table() -> tuple[Table, Index, Index]:
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    Table(
        "parents",
        metadata,
        Column("a", Integer, primary_key=True),
        Column("b", Integer, primary_key=True),
    )
    table = Table(
        "memberships",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("group_id", Integer),
        Column("user_id", Integer),
        Column("color_index", Integer),
        UniqueConstraint("group_id", "user_id"),
        UniqueConstraint("group_id", "color_index"),
        ForeignKeyConstraint(["group_id", "user_id"], ["parents.a", "parents.b"]),
        ForeignKeyConstraint(["group_id", "color_index"], ["parents.a", "parents.b"]),
    )
    first = Index(None, table.c.group_id, table.c.user_id)
    second = Index(None, table.c.group_id, table.c.color_index)
    return table, first, second


def _render(table: Table, *indexes: Index) -> str:
    # Compiling resolves the convention-based names.
    return "\n".join([str(CreateTable(table))] + [str(CreateIndex(ix)) for ix in indexes])


def test_composite_unique_constraints_get_distinct_names() -> None:
    table, *_ = _composite_table()
    ddl = _render(table)

    assert "uq_memberships_group_id_user_id" in ddl
    assert "uq_memberships_group_id_color_index" in ddl


def test_composite_foreign_keys_get_distinct_names() -> None:
    table, *_ = _composite_table()
    ddl = _render(table)

    assert "fk_memberships_group_id_user_id_parents" in ddl
    assert "fk_memberships_group_id_color_index_parents" in ddl


def test_composite_indexes_get_distinct_names() -> None:
    table, first, second = _composite_table()
    ddl = _render(table, first, second)

    assert "ix_memberships_group_id_user_id" in ddl
    assert "ix_memberships_group_id_color_index" in ddl
