"""Turning fired checks into a verdict.

The numbers below are judgements, and almost certainly not the right ones yet.
That is the point: they are judgements you can read, test, tune and argue with
in review. The version this replaces was a number a language model picked, which
could not be reproduced, explained or adjusted.

There is deliberately no "safe" outcome. The system can say "this is a scam" or
"we could not confirm this" - never "this is fine". A false reassurance is the
one mistake that costs someone their savings.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .checks import CheckResult, run_checks
from .taxonomy import LureType, Signals


class Outcome(str, Enum):
    SCAM = "SCAM"
    COULDNT_CONFIRM = "COULDNT_CONFIRM"


# Checks that decide the verdict on their own. Reserved for cases where a benign
# explanation is hard to construct: a real agency does not send you to a domain
# it does not own.
HARD_TRIGGERS = frozenset({"C2"})

# Everything else contributes points. C3 is deliberately not a hard trigger:
# brand-token matching can misfire, and a false SCAM verdict trains people to
# ignore the true ones.
CHECK_POINTS = {
    "C1": 15,
    "C2": 100,  # also a hard trigger; scored so the number reflects severity
    "C3": 45,
    "C4": 40,
    "C5": 35,
    "C7": 20,
}

POINTS_PER_TACTIC = 5
MAX_TACTIC_POINTS = 20
POINTS_FOR_LURE = 10

SCAM_THRESHOLD = 60


@dataclass(frozen=True)
class Verdict:
    outcome: Outcome
    score: int
    hardTriggered: tuple[str, ...]
    checks: tuple[CheckResult, ...]

    @property
    def reasons(self) -> tuple[str, ...]:
        """Why this verdict, in the order the checks ran."""
        return tuple(c.detail for c in self.checks if c.fired and c.detail)


def score_signals(signals: Signals, checks: tuple[CheckResult, ...]) -> int:
    total = sum(CHECK_POINTS.get(c.id, 0) for c in checks if c.fired)
    total += min(len(signals.pressureTactics) * POINTS_PER_TACTIC, MAX_TACTIC_POINTS)
    if signals.lureType is not LureType.NONE:
        total += POINTS_FOR_LURE
    return min(total, 100)


def decide(signals: Signals) -> Verdict:
    """Run every check and turn the results into a verdict.

    Pure: the same signals always produce the same verdict, so a disputed result
    can be reproduced exactly from the stored signals.
    """
    checks = run_checks(signals)
    hard = tuple(c.id for c in checks if c.fired and c.id in HARD_TRIGGERS)
    score = score_signals(signals, checks)

    outcome = (
        Outcome.SCAM if hard or score >= SCAM_THRESHOLD else Outcome.COULDNT_CONFIRM
    )
    return Verdict(outcome=outcome, score=score, hardTriggered=hard, checks=checks)
