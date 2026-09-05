"""What a user is vulnerable to, derived from what they have checked.

Two rules from the workflow doc, expressed as one formula:

    vulnerability[lure] = sum over encounters with that lure of
                              depth_weight * 0.5 ** (age_days / HALF_LIFE)

Recency is the exponential term: a vulnerability halves every 90 days unless it
recurs, so "old vulnerabilities fade if they stop recurring" is arithmetic
rather than a policy someone has to remember to apply. Depth is the weight:
someone who nearly transferred money counts for more than someone who checked
before replying.

Scores are derived on read rather than stored, so the weights below can change
without migrating anything. The encounters are the record; everything else is a
view of them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pattern.taxonomy import Channel, EngagementDepth, LureType, PressureTactic

# A vulnerability halves every this many days without recurrence.
HALF_LIFE_DAYS = 90.0

# How much an encounter counts, by how far the user went before checking.
# Someone who checked before replying still counts: choosing to check at all
# says something about what they find plausible, which is why every analysis is
# recorded and not only the ones that turned out to be scams.
DEPTH_WEIGHT = {
    EngagementDepth.NO_REPLY: 1.0,
    EngagementDepth.REPLIED: 2.0,
    EngagementDepth.SHARED_PERSONAL_INFO: 4.0,
    EngagementDepth.SHARED_CREDENTIALS: 6.0,
    EngagementDepth.INITIATED_PAYMENT: 8.0,
}


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

    def weight_at(self, now: datetime) -> float:
        """This encounter's contribution, faded by how long ago it happened."""
        age_days = max(0.0, (now - self.at).total_seconds() / 86400.0)
        decay = math.pow(0.5, age_days / HALF_LIFE_DAYS)
        return DEPTH_WEIGHT[self.engagementDepth] * decay


@dataclass(frozen=True)
class Profile:
    """A user's risk shape. Derived, never stored."""

    userId: str
    encounterCount: int
    vulnerability: dict[str, float] = field(default_factory=dict)
    tacticSensitivity: dict[str, float] = field(default_factory=dict)
    channels: dict[str, int] = field(default_factory=dict)

    def top_lure(self) -> str | None:
        return max(self.vulnerability, key=self.vulnerability.get, default=None)

    def usual_channel(self) -> str | None:
        known = {c: n for c, n in self.channels.items() if c != Channel.UNKNOWN.value}
        return max(known, key=known.get, default=None)


def build_profile(
    userId: str, encounters: list[Encounter], now: datetime | None = None
) -> Profile:
    """Fold a user's history into current vulnerability scores.

    `now` is a parameter rather than a call to the clock so the decay can be
    tested: a formula that depends on the wall clock cannot be asserted about.
    """
    now = now or datetime.now(timezone.utc)

    vulnerability: dict[str, float] = {}
    tactics: dict[str, float] = {}
    channels: dict[str, int] = {}

    for e in encounters:
        weight = e.weight_at(now)

        if e.lureType is not LureType.NONE:
            vulnerability[e.lureType.value] = (
                vulnerability.get(e.lureType.value, 0.0) + weight
            )
        for tactic in e.pressureTactics:
            tactics[tactic.value] = tactics.get(tactic.value, 0.0) + weight
        channels[e.channel.value] = channels.get(e.channel.value, 0) + 1

    return Profile(
        userId=userId,
        encounterCount=len(encounters),
        vulnerability={k: round(v, 4) for k, v in vulnerability.items()},
        tacticSensitivity={k: round(v, 4) for k, v in tactics.items()},
        channels=channels,
    )
