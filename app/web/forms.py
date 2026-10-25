from flask_wtf import FlaskForm
from wtforms import HiddenField, SelectField, StringField

from app.services.voting import Choice


class EmailForm(FlaskForm):
    email = StringField()


class NameForm(FlaskForm):
    display_name = StringField()


class GroupNameForm(FlaskForm):
    name = StringField()


class ConfirmNameForm(FlaskForm):
    """Destructive actions are confirmed by typing the group name (GRP-04, A5)."""

    confirmation = StringField()


class ConfirmForm(FlaskForm):
    """A plain button; the form only carries the CSRF token."""


class LogoutForm(FlaskForm):
    next = HiddenField()
    endpoint = HiddenField()  # this device's push subscription, filled in by push.js


class VoteForm(FlaskForm):
    choice = SelectField(choices=[choice.value for choice in Choice])


class ReasonForm(FlaskForm):
    reason = StringField()
