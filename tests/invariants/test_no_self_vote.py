"""VOT-03: nobody can rate themselves, neither through the service nor in the database."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Vote
from app.services import periods
from app.services.errors import InvalidInput
from tests.factories import IN_WEEK_WINDOW, add_member, make_group, tick, vote


@pytest.fixture
def group(app, clock):
    group = make_group()
    add_member(group)
    clock.set(IN_WEEK_WINDOW)
    tick()
    return group


def test_service_refuses(group):
    with pytest.raises(InvalidInput):
        vote(group, group.admin, group.admin, "up")


def test_database_refuses(group, clock):
    admin_id = group.admin_user_id
    db.session.add(
        Vote(
            period_id=periods.open_period(group.id).id,
            voter_user_id=admin_id,
            target_user_id=admin_id,
            value=1,
            created_at=clock.now(),
            updated_at=clock.now(),
        )
    )
    with pytest.raises(IntegrityError, match="no_self_vote"):
        db.session.commit()


@pytest.mark.parametrize("value", [0, 2, -2])
def test_database_refuses_other_values(group, clock, value):
    db.session.add(
        Vote(
            period_id=periods.open_period(group.id).id,
            voter_user_id=group.admin_user_id,
            target_user_id=group.admin_user_id + 1,
            value=value,
            created_at=clock.now(),
            updated_at=clock.now(),
        )
    )
    with pytest.raises(IntegrityError, match="ck_votes_value"):
        db.session.commit()
