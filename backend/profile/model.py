"""What a user is vulnerable to, derived from what they have checked.

Vulnerability is a count: how many times this person has been approached with
each kind of scam. Whole numbers, because the screen shows them to the person
they are about and "authority 8.14" invites the question what 8.14 means.

An earlier version weighted each encounter by how far the user went and faded it
exponentially with age, so that recent and deeper encounters counted for more.
That is in the workflow doc as "recent matters more" and "depth matters", and it
is worth having - but not at the cost of a number nobody can read. The
ingredients are still in the database (every encounter keeps its timestamp and
depth) and these scores are derived on read, so weighting can come back without
a migration whenever there is a place to show it that is not the user's face.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from pattern.taxonomy import Channel, EngagementDepth, LureType, PressureTactic


@dataclass(frozen=True)
class Encounter:
    """One conversation a user asked us to check."""

    userId: str
    at: datetime
    lureType: LureType
    pressureTactics: tuple[PressureTactic, ...]
    channel: Channel
    engagementDepth: EngagementDepth
    outcome: str  # "SCAM" or "COULDNT_CONFIRM"
    score: int
    recordingId: str = ""


@dataclass(frozen=True)
class Profile:
    """A user's risk shape. Derived, never stored."""

    userId: str
    encounterCount: int
    # How many times each lure and tactic has been used on this person.
    vulnerability: dict[str, int] = field(default_factory=dict)
    tacticSensitivity: dict[str, int] = field(default_factory=dict)
    channels: dict[str, int] = field(default_factory=dict)
    lureCounts: dict[str, int] = field(default_factory=dict)

    def top_lure(self) -> str | None:
        return max(self.vulnerability, key=self.vulnerability.get, default=None)

    def usual_channel(self) -> str | None:
        known = {c: n for c, n in self.channels.items() if c != Channel.UNKNOWN.value}
        return max(known, key=known.get, default=None)


def build_profile(
    userId: str, encounters: list[Encounter], now: datetime | None = None
) -> Profile:
    """Fold a user's history into counts.

    `now` is accepted and unused: the caller should not have to know whether the
    current scores depend on the time, and re-introducing the age weighting
    should not change every call site.
    """
    vulnerability: dict[str, int] = {}
    tactics: dict[str, int] = {}
    channels: dict[str, int] = {}

    for e in encounters:
        if e.lureType is not LureType.NONE:
            vulnerability[e.lureType.value] = vulnerability.get(e.lureType.value, 0) + 1
        for tactic in e.pressureTactics:
            tactics[tactic.value] = tactics.get(tactic.value, 0) + 1
        channels[e.channel.value] = channels.get(e.channel.value, 0) + 1

    return Profile(
        userId=userId,
        encounterCount=len(encounters),
        vulnerability=vulnerability,
        tacticSensitivity=tactics,
        channels=channels,
        # Same numbers as `vulnerability` while scores are plain counts. Kept
        # separate because they answer different questions: one is "how exposed
        # is this person", the other is "how many times has this happened", and
        # they diverge again as soon as weighting returns.
        lureCounts=dict(vulnerability),
    )
