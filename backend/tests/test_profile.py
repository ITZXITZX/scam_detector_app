"""Tests for the profile.

The two rules from the workflow doc are the two things worth asserting: recent
matters more, and depth matters. Both are arithmetic, so both can be tested
exactly - `now` is passed in rather than read from the clock.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pattern.taxonomy import (  # noqa: E402
    Channel,
    EngagementDepth,
    LureType,
    PressureTactic,
)
from profile.model import Encounter, build_profile  # noqa: E402
from profile.store import get_profile, load_encounters, record_encounter  # noqa: E402

NOW = datetime(2026, 9, 6, tzinfo=timezone.utc)


def encounter(
    *,
    days_ago: float = 0,
    lure: LureType = LureType.AUTHORITY,
    depth: EngagementDepth = EngagementDepth.REPLIED,
    tactics: tuple[PressureTactic, ...] = (),
    channel: Channel = Channel.WHATSAPP,
    outcome: str = "SCAM",
) -> Encounter:
    return Encounter(
        userId="u1",
        at=NOW - timedelta(days=days_ago),
        lureType=lure,
        pressureTactics=tactics,
        channel=channel,
        engagementDepth=depth,
        outcome=outcome,
        score=100,
    )


# --------------------------------------------------------------------------
# Counts
#
# Vulnerability is a plain count of how many times each lure has been used on
# this person. The age weighting that used to fade old encounters was removed
# because the number is shown to the user and "authority 8.14" is not readable.
# Every encounter still stores its timestamp and depth, so weighting can return
# without a migration.
# --------------------------------------------------------------------------


def test_vulnerability_counts_encounters():
    profile = build_profile(
        "u1",
        [encounter(), encounter(), encounter(lure=LureType.PHISHING)],
        now=NOW,
    )
    assert profile.vulnerability == {"authority": 2, "phishing": 1}
    assert profile.top_lure() == "authority"


def test_counts_are_whole_numbers():
    """Shown to the user, so they have to be readable as facts."""
    profile = build_profile("u1", [encounter()] * 3, now=NOW)
    assert profile.vulnerability["authority"] == 3
    assert all(isinstance(v, int) for v in profile.vulnerability.values())
    assert all(isinstance(v, int) for v in profile.tacticSensitivity.values())


def test_age_no_longer_changes_the_count():
    fresh = build_profile("u1", [encounter(days_ago=0)], now=NOW)
    ancient = build_profile("u1", [encounter(days_ago=3000)], now=NOW)
    assert fresh.vulnerability == ancient.vulnerability


def test_depth_no_longer_changes_the_count():
    cautious = build_profile("u1", [encounter(depth=EngagementDepth.NO_REPLY)], now=NOW)
    exposed = build_profile(
        "u1", [encounter(depth=EngagementDepth.INITIATED_PAYMENT)], now=NOW
    )
    assert cautious.vulnerability == exposed.vulnerability


def test_depth_and_timestamp_are_still_recorded(tmp_path):
    """The ingredients for weighting survive, even though nothing uses them."""
    db = tmp_path / "t.db"
    record_encounter(
        encounter(days_ago=12, depth=EngagementDepth.INITIATED_PAYMENT), db_path=db
    )
    loaded = load_encounters("u1", db_path=db)[0]
    assert loaded.engagementDepth is EngagementDepth.INITIATED_PAYMENT
    assert loaded.at == NOW - timedelta(days=12)


# --------------------------------------------------------------------------
# The sentence the workflow doc asks for
# --------------------------------------------------------------------------


def test_profile_describes_the_users_shape():
    """Targeted mostly with authority scams, never with parcel scams,
    usually on WhatsApp."""
    profile = build_profile(
        "u1",
        [
            encounter(days_ago=3, lure=LureType.AUTHORITY,
                      depth=EngagementDepth.SHARED_PERSONAL_INFO,
                      tactics=(PressureTactic.URGENCY, PressureTactic.ISOLATION)),
            encounter(days_ago=20, lure=LureType.AUTHORITY,
                      tactics=(PressureTactic.URGENCY,)),
            encounter(days_ago=40, lure=LureType.INVESTMENT, channel=Channel.TELEGRAM),
        ],
        now=NOW,
    )
    assert profile.top_lure() == "authority"
    assert profile.usual_channel() == "whatsapp"
    assert "phishing" not in profile.vulnerability
    assert profile.tacticSensitivity["urgency"] > profile.tacticSensitivity["isolation"]


def test_checking_something_harmless_still_counts():
    """Every analysis is recorded, not only the scams.

    A user who checks parcel messages that turn out to be fine is telling us
    something about what they find plausible - and the early catches are what
    make a vulnerability visibly fade.
    """
    profile = build_profile(
        "u1",
        [encounter(lure=LureType.PHISHING, outcome="COULDNT_CONFIRM",
                   depth=EngagementDepth.NO_REPLY)],
        now=NOW,
    )
    assert profile.encounterCount == 1
    assert "phishing" in profile.vulnerability


def test_unlabelled_lure_does_not_create_a_vulnerability():
    profile = build_profile("u1", [encounter(lure=LureType.NONE)], now=NOW)
    assert profile.vulnerability == {}
    assert profile.encounterCount == 1


def test_new_user_has_an_empty_profile():
    profile = build_profile("nobody", [], now=NOW)
    assert profile.encounterCount == 0
    assert profile.top_lure() is None
    assert profile.usual_channel() is None


def test_unknown_channel_is_not_reported_as_the_usual_one():
    """`channel` is often "unknown", and an unknown is not a habit."""
    profile = build_profile(
        "u1",
        [
            encounter(channel=Channel.UNKNOWN),
            encounter(channel=Channel.UNKNOWN),
            encounter(channel=Channel.TELEGRAM),
        ],
        now=NOW,
    )
    assert profile.usual_channel() == "telegram"


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------


def test_encounters_round_trip_through_sqlite(tmp_path):
    db = tmp_path / "t.db"
    original = encounter(
        days_ago=5,
        tactics=(PressureTactic.URGENCY, PressureTactic.SECRECY),
        channel=Channel.TELEGRAM,
    )
    record_encounter(original, db_path=db)

    loaded = load_encounters("u1", db_path=db)
    assert len(loaded) == 1
    assert loaded[0].lureType is original.lureType
    assert loaded[0].pressureTactics == original.pressureTactics
    assert loaded[0].channel is Channel.TELEGRAM
    assert loaded[0].at == original.at


def test_profiles_are_isolated_per_user(tmp_path):
    db = tmp_path / "t.db"
    record_encounter(encounter(lure=LureType.AUTHORITY), db_path=db)
    other = Encounter(
        userId="u2", at=NOW, lureType=LureType.ROMANCE, pressureTactics=(),
        channel=Channel.WHATSAPP, engagementDepth=EngagementDepth.REPLIED,
        outcome="SCAM", score=70,
    )
    record_encounter(other, db_path=db)

    assert get_profile("u1", now=NOW, db_path=db).top_lure() == "authority"
    assert get_profile("u2", now=NOW, db_path=db).top_lure() == "romance"


def test_no_message_content_is_stored(tmp_path):
    """A profile is the shape of a risk, never a record of conversations.

    Workflow D promises a family member sees the shape and never the content.
    That promise is easiest to keep if the content was never written down.
    """
    import sqlite3

    db = tmp_path / "t.db"
    record_encounter(encounter(), db_path=db)
    columns = {
        r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(encounters)")
    }
    assert not ({"text", "message", "transcript", "url", "urls"} & columns)
