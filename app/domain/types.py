"""Value types shared by the domain modules."""

from enum import StrEnum
from typing import NewType

UserId = NewType("UserId", int)


class Cadence(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
