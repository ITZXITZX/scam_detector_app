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
from profile.model import HALF_LIFE_DAYS, Encounter, build_profile  # noqa: E402
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
# Rule: recent matters more
# --------------------------------------------------------------------------


def test_a_vulnerability_halves_over_one_half_life():
    fresh = build_profile("u1", [encounter(days_ago=0)], now=NOW)
    old = build_profile("u1", [encounter(days_ago=HALF_LIFE_DAYS)], now=NOW)
    assert old.vulnerability["authority"] == pytest.approx(
        fresh.vulnerability["authority"] / 2, rel=1e-3
    )


def test_an_old_vulnerability_fades_below_a_recent_one():
    """Old vulnerabilities fade if they stop recurring: two encounters a year
    ago should not outweigh one from last week."""
    profile = build_profile(
        "u1",
        [
            encounter(days_ago=365, lure=LureType.PARCEL),
            encounter(days_ago=365, lure=LureType.PARCEL),
            encounter(days_ago=7, lure=LureType.AUTHORITY),
        ],
        now=NOW,
    )
    assert profile.vulnerability["authority"] > profile.vulnerability["parcel"]
    assert profile.top_lure() == "authority"


def test_repeated_recent_encounters_accumulate():
    once = build_profile("u1", [encounter(days_ago=1)], now=NOW)
    thrice = build_profile("u1", [encounter(days_ago=1)] * 3, now=NOW)
    assert thrice.vulnerability["authority"] > once.vulnerability["authority"]


# --------------------------------------------------------------------------
# Rule: depth matters
# --------------------------------------------------------------------------


def test_nearly_paying_counts_for_more_than_checking_early():
    """Someone who nearly transferred money counts more than someone who
    checked immediately."""
    cautious = build_profile(
        "u1", [encounter(depth=EngagementDepth.NO_REPLY)], now=NOW
    )
    exposed = build_profile(
        "u1", [encounter(depth=EngagementDepth.INITIATED_PAYMENT)], now=NOW
    )
    assert exposed.vulnerability["authority"] > cautious.vulnerability["authority"]


def test_one_deep_encounter_outweighs_several_shallow_ones():
    shallow = build_profile(
        "u1", [encounter(depth=EngagementDepth.NO_REPLY)] * 5, now=NOW
    )
    deep = build_profile(
        "u1", [encounter(depth=EngagementDepth.SHARED_CREDENTIALS)], now=NOW
    )
    assert deep.vulnerability["authority"] > shallow.vulnerability["authority"] / 5


# --------------------------------------------------------------------------
# The sentence the workflow doc asks for
# --------------------------------------------------------------------------


def test_profile_describes_the_users_shape():
    """Highly vulnerable to authority scams, not at all to parcel scams.
    Usually targeted on WhatsApp."""
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
    assert "parcel" not in profile.vulnerability
    assert profile.tacticSensitivity["urgency"] > profile.tacticSensitivity["isolation"]


def test_checking_something_harmless_still_counts():
    """Every analysis is recorded, not only the scams.

    A user who checks parcel messages that turn out to be fine is telling us
    something about what they find plausible - and the early catches are what
    make a vulnerability visibly fade.
    """
    profile = build_profile(
        "u1",
        [encounter(lure=LureType.PARCEL, outcome="COULDNT_CONFIRM",
                   depth=EngagementDepth.NO_REPLY)],
        now=NOW,
    )
    assert profile.encounterCount == 1
    assert "parcel" in profile.vulnerability


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
