"""Scam waves circulating now, and who should be told about them.

A campaign is news: dated, short-lived, written from a police advisory. That is
what separates it from the guidance in `knowledge/scamshield.yaml`, which is
reference material and does not go stale. Both are written in the same taxonomy,
which is what lets a campaign be matched against a profile with arithmetic
rather than another model call.

The text a user receives is stored here, authored once and reviewed once. It is
never generated per recipient: a message that goes unprompted to other people's
phones has to be read by a person before it is sent, and it cannot be read if it
is different every time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum

from pattern.taxonomy import Channel, ClaimedIdentity, LureType, PressureTactic


class Severity(str, Enum):
    """How much this campaign is allowed to interrupt someone.

    Only used to break ties: when a user's weekly quota is spent, a HIGH
    campaign may displace a warning that has not been sent yet, and a NORMAL one
    may not.
    """

    NORMAL = "normal"
    HIGH = "high"


@dataclass(frozen=True)
class Campaign:
    """One scam wave, described in the same vocabulary as a user profile."""

    id: str
    title: str            # notification title - what is circulating
    body: str             # notification body - what it sounds like, and the fact
                          # that makes it checkable
    lureType: LureType
    tactics: tuple[PressureTactic, ...] = ()
    channel: Channel = Channel.UNKNOWN
    claimedIdentity: ClaimedIdentity = ClaimedIdentity.NONE
    severity: Severity = Severity.NORMAL
    activeFrom: date | None = None
    activeUntil: date | None = None
    source: str = ""      # the advisory this was written from
    approved: bool = False  # a person has read the text that will be sent

    def is_active(self, on: date | None = None) -> bool:
        on = on or datetime.now(timezone.utc).date()
        if self.activeFrom and on < self.activeFrom:
            return False
        if self.activeUntil and on > self.activeUntil:
            return False
        return True


@dataclass(frozen=True)
class Match:
    """Why a campaign was, or was not, matched to a profile."""

    campaignId: str
    userId: str
    matched: bool
    score: int
    reason: str
    detail: dict[str, int] = field(default_factory=dict)
