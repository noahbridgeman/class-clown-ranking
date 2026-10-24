"""NFA-12: the group page and the graph of a full group with a year of daily periods.

The budgets are far below the 2 seconds of NFA-12, which also cover network and
rendering on the phone. The query count must not grow with the number of periods.
"""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta

import pytest
from sqlalchemy import event, insert

from app.domain import scoring
from app.domain.types import Cadence
from app.extensions import db
from app.models import Group, Period, PeriodResult, PeriodStatus, User
from tests.factories import add_member, make_daily, make_group, make_user

MEMBERS = 30  # MAX_GROUP_SIZE (A8)
DAYS = 365
MAX_QUERIES = 12
MAX_SECONDS = 1.0  # generous for slow CI runners; measured about 0.05 s
MAX_YEAR_BYTES = 200_000  # uncompressed; the default range of 4 weeks is far smaller


@pytest.fixture
def full_year(app, clock) -> tuple[Group, User]:
    """30 members and 365 closed daily periods, inserted in bulk."""
    users = [make_user(display_name=f"Person {i}") for i in range(MEMBERS)]
    group = make_daily(make_group(users[0]))
    for user in users[1:]:
        add_member(group, user)
    params = scoring.default_params(Cadence.DAILY)
    start = clock.now() - timedelta(days=DAYS)
    db.session.execute(
        insert(Period),
        [
            {
                "group_id": group.id,
                "seq": day + 1,
                "opens_at": start + timedelta(days=day),
                "closes_at": start + timedelta(days=day + 1),
                "cadence": Cadence.DAILY,
                "is_anonymous": day % 90 < 45,
                "k": params.k,
                "d": params.d,
                "status": PeriodStatus.CLOSED,
                "closed_at": start + timedelta(days=day + 1),
            }
            for day in range(DAYS)
        ],
    )
    period_ids = db.session.scalars(
        db.select(Period.id).where(Period.group_id == group.id).order_by(Period.seq)
    ).all()
    ratings = {user.id: 0.0 for user in users}
    rows = []
    for day, period_id in enumerate(period_ids):
        for i, user in enumerate(users):
            ups, downs = (day + i) % 4, (day * i) % 3
            net = scoring.net(ups, downs)
            after = scoring.next_rating(ratings[user.id], net, params)
            rows.append(
                {
                    "period_id": period_id,
                    "user_id": user.id,
                    "ups": ups,
                    "downs": downs,
                    "net": net,
                    "rating_before": ratings[user.id],
                    "rating_after": after,
                    "score": scoring.score(after),
                }
            )
            ratings[user.id] = after
    db.session.execute(insert(PeriodResult), rows)
    db.session.commit()
    return group, users[0]


@contextmanager
def count_queries() -> Iterator[list[str]]:
    statements: list[str] = []

    def record(_conn, _cursor, statement, *_args) -> None:
        statements.append(statement)

    event.listen(db.engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(db.engine, "before_cursor_execute", record)


@pytest.mark.parametrize(
    "path", ["/", "/graph.json", "/graph.json?range=1y", "/graph.json?range=all"]
)
def test_full_group_loads_fast(full_year, login_as, path):
    group, user = full_year
    client = login_as(user)
    url = f"/g/{group.id}{path}"
    client.get(url)  # warm up templates and caches
    with count_queries() as statements:
        started = time.perf_counter()
        response = client.get(url)
        elapsed = time.perf_counter() - started
    assert response.status_code == 200
    assert len(statements) <= MAX_QUERIES, statements
    assert elapsed < MAX_SECONDS


def test_a_year_has_every_point(full_year, login_as):
    group, user = full_year
    response = login_as(user).get(f"/g/{group.id}/graph.json?range=all")
    assert len(response.data) < MAX_YEAR_BYTES
    body = response.get_json()
    assert len(body["periods"]) == DAYS
    assert len(body["series"]) == MEMBERS
    assert all(len(s["points"]) == DAYS for s in body["series"])
