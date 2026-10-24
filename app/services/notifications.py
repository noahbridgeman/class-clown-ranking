"""Messages to members. Mail only for now; push follows in M8."""

from flask import current_app

from app.i18n import t
from app.models import Group, Invitation, User
from app.services import mail
from app.services.text import member_name


def admin_granted(user: User, group: Group) -> bool:
    """Section 11: the new admin hears about it by mail (and from M8 on by push)."""
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
