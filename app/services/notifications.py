"""Messages to members (section 11, A24): mail for account matters, push for voting.

Decides what goes to whom; app.services.push filters by preferences and delivers.
No message ever says who voted how (NOT-04): only windows, one's own progress, one's
own score and changes of place, which the leaderboard shows anyway.
"""

from datetime import datetime

from flask import current_app
from sqlalchemy import select

from app.domain import ranking, scoring
from app.domain.formatting import format_change, format_score
from app.domain.types import UserId
from app.extensions import db
from app.i18n import short_datetime, t
from app.models import (
    Group,
    Invitation,
    Membership,
    NotificationKind,
    Period,
    PeriodResult,
    PeriodStatus,
    SettingsChange,
    User,
)
from app.services import mail, membership, push, settings, vote_queries
from app.services.push import Delivery, Push
from app.services.text import member_name

# Mail


def admin_granted(user: User, group: Group) -> bool:
    """Section 11: the new admin hears about it by mail and push (ROL-02, ROL-03)."""
    push.deliver(
        [
            Delivery(
                user.id,
                group.id,
                NotificationKind.ADMIN_GRANTED,
                Push(
                    group.name,
                    t("push.admin_granted"),
                    _path(group, "settings"),
                    _tag(group, "admin"),
                ),
            )
        ]
    )
    if user.email is None:
        return False
    return mail.try_send(
        mail.Mail(
            to=user.email,
            subject=t("mail.admin_granted_subject", group=group.name),
            body=t("mail.admin_granted_body", group=group.name, link=group_link(group)),
        )
    )


def invitation(invitation: Invitation, link: str) -> bool:
    days = current_app.config["INVITATION_LIFETIME"].days
    inviter = member_name(invitation.invited_by)
    return mail.try_send(
        mail.Mail(
            to=invitation.email,
            subject=t("mail.invitation_subject", inviter=inviter, group=invitation.group.name),
            body=t(
                "mail.invitation_body",
                inviter=inviter,
                group=invitation.group.name,
                link=link,
                days=days,
            ),
        )
    )


def group_link(group: Group) -> str:
    return f"{current_app.config['BASE_URL']}/g/{group.id}"


# Push from the period update


def period_events(group: Group, now: datetime) -> list[Delivery]:
    """The pushes due for a group, inside tick's locked transaction (PER-01 step 5).

    Sets each period's flag right away, so the commit that follows makes it final and a
    second run sends nothing again (NOT-03, PER-02). Does not commit.
    """
    members = membership.active_members(group.id)
    deliveries: list[Delivery] = []
    for period in _unannounced_results(group.id):
        period.results_notified_at = now
        deliveries += _scores_published(group, period, members)
    open_period = db.session.scalar(
        select(Period).where(Period.group_id == group.id, Period.status == PeriodStatus.OPEN)
    )
    if open_period is None or now >= open_period.closes_at:
        return deliveries
    if open_period.opened_notified_at is None:
        open_period.opened_notified_at = now
        deliveries += _window_open(group, open_period, members)
    reminder_at = open_period.closes_at - current_app.config["REMINDER_BEFORE_CLOSE"]
    if open_period.reminder_sent_at is None and now >= reminder_at:
        open_period.reminder_sent_at = now
        deliveries += _reminder(group, open_period, members)
    return deliveries


def _unannounced_results(group_id: int) -> list[Period]:
    """Also periods closed by a join or leave, not only by tick (plan section 5)."""
    return list(
        db.session.scalars(
            select(Period)
            .where(
                Period.group_id == group_id,
                Period.status == PeriodStatus.CLOSED,
                Period.results_notified_at.is_(None),
            )
            .order_by(Period.seq)
        )
    )


def _window_open(group: Group, period: Period, members: list[Membership]) -> list[Delivery]:
    body = t("push.window_open", end=short_datetime(period.closes_at, group.timezone))
    message = Push(group.name, body, _path(group, "vote"), _tag(group, "voting"))
    return [Delivery(m.user_id, group.id, NotificationKind.WINDOW_OPEN, message) for m in members]


def _reminder(group: Group, period: Period, members: list[Membership]) -> list[Delivery]:
    """Only to those who have not rated everyone else yet (section 11)."""
    cast = vote_queries.votes_cast(period)
    total = len(members) - 1
    # The end, not "2 hours left": after downtime the reminder may come later (NOT-03).
    end = short_datetime(period.closes_at, group.timezone)
    deliveries = []
    for m in members:
        done = cast.get(m.user_id, 0)
        if total < 1 or done >= total:
            continue
        body = t("push.reminder", end=end, done=done, total=total)
        message = Push(group.name, body, _path(group, "vote"), _tag(group, "voting"))
        deliveries.append(Delivery(m.user_id, group.id, NotificationKind.REMINDER, message))
    return deliveries


def _scores_published(group: Group, period: Period, members: list[Membership]) -> list[Delivery]:
    results = {
        r.user_id: r
        for r in db.session.scalars(select(PeriodResult).where(PeriodResult.period_id == period.id))
    }
    deliveries = []
    for m in members:
        result = results.get(m.user_id)
        if result is None:  # joined after the window: no score of their own yet (A24)
            continue
        change = ranking.displayed_change(scoring.score(result.rating_before), result.score)
        body = t(
            "push.scores_published",
            score=format_score(result.score),
            change=format_change(change, compact=True),
        )
        message = Push(group.name, body, _path(group), _tag(group, "scores"))
        deliveries.append(Delivery(m.user_id, group.id, NotificationKind.SCORES_PUBLISHED, message))
    return deliveries + _overtaken(group, period, results, members)


def _overtaken(
    group: Group, period: Period, results: dict[int, PeriodResult], members: list[Membership]
) -> list[Delivery]:
    """Both sides of every change of place in this period, among members with a score
    before and after it (A24); newcomers overtake nobody."""
    earlier = set(
        db.session.scalars(
            select(PeriodResult.user_id)
            .join(Period, Period.id == PeriodResult.period_id)
            .where(Period.group_id == group.id, Period.seq < period.seq)
        )
    )
    active = {m.user_id: m.user for m in members}
    compared = [u for u in results if u in earlier and u in active]
    prev = {UserId(u): scoring.score(results[u].rating_before) for u in compared}
    curr = {UserId(u): results[u].score for u in compared}
    passed: dict[int, list[int]] = {}
    passed_by: dict[int, list[int]] = {}
    for overtaker, overtaken in ranking.overtakes(prev, curr):
        passed.setdefault(overtaker, []).append(overtaken)
        passed_by.setdefault(overtaken, []).append(overtaker)

    def names(user_ids: list[int]) -> str:
        return t("ranking.list_separator").join(member_name(active[u]) for u in user_ids)

    deliveries = []
    for user_id in active:
        lines = []
        if user_id in passed:
            lines.append(t("push.overtook", names=names(passed[user_id])))
        if user_id in passed_by:
            key = (
                "push.overtaken_by_one"
                if len(passed_by[user_id]) == 1
                else "push.overtaken_by_many"
            )
            lines.append(t(key, names=names(passed_by[user_id])))
        if lines:
            message = Push(group.name, " ".join(lines), _path(group), _tag(group, "overtaken"))
            deliveries.append(Delivery(user_id, group.id, NotificationKind.OVERTAKEN, message))
    return deliveries


# Push from requests


def settings_changed(
    group: Group, actor: User, changes: list[SettingsChange], now: datetime
) -> int:
    """After the admin saved (A24): to everyone else, with the fields and when they apply."""
    if not changes:
        return 0
    fields = list(dict.fromkeys(c.field for c in changes))
    labels = t("ranking.list_separator").join(t(settings.FIELD_LABELS[f]) for f in fields)
    upcoming = settings.upcoming(group)
    start = short_datetime(settings.takes_effect_at(group, now), upcoming.timezone)
    message = Push(
        group.name,
        t("push.settings_changed", fields=labels, start=start),
        _path(group, "settings"),
        _tag(group, "settings"),
    )
    return push.deliver(
        Delivery(m.user_id, group.id, NotificationKind.SETTINGS_CHANGED, message)
        for m in membership.active_members(group.id)
        if m.user_id != actor.id
    )


def _path(group: Group, page: str = "") -> str:
    return f"/g/{group.id}/{page}"


def _tag(group: Group, topic: str) -> str:
    return f"g{group.id}-{topic}"
