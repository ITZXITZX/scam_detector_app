"""Persistence for encounters.

SQLite from the standard library: no new dependency, no server to run, and the
file can be opened and inspected with any sqlite client when a profile looks
wrong.

Only encounters are stored. Vulnerability scores are derived on read, so the
decay half-life and depth weights can be changed without a migration - useful,
because those numbers are guesses that will move.

Deliberately NOT stored: message text, URLs, or anything identifying the other
party. A profile is the shape of what someone is vulnerable to, not a record of
their conversations. Workflow D shows a family member that shape and never the
content, and that promise is easiest to keep if the content was never written
down.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from pattern.taxonomy import Channel, EngagementDepth, LureType, PressureTactic

from .model import Encounter, Profile, build_profile

# Labels that were stored before the taxonomy changed, and where they belong
# now. The lure enum was aligned to ScamShield's categories after rows already
# existed, and "parcel" stopped being one of them - ScamShield treats parcel
# delivery messages as a phishing variant.
_RENAMED_LURES = {
    "parcel": "phishing",
    "lottery": "other",
    "impersonation_known_person": "fake_friend",
}


def _coerce(enum_cls, value: str, renames: dict[str, str] | None = None):
    """Read a stored label, tolerating one this build no longer knows.

    Enum values are written into the database, so removing one strands every
    row that used it. A stranded row should not be able to take down a whole
    profile: the honest failure is to lose that encounter's category, not the
    user's history. Known renames are mapped; anything else falls back.
    """
    if renames and value in renames:
        value = renames[value]
    try:
        return enum_cls(value)
    except ValueError:
        # `other`/`unknown`/first-member, in that order of preference.
        for fallback in ("other", "unknown"):
            try:
                return enum_cls(fallback)
            except ValueError:
                continue
        return next(iter(enum_cls))

DB_PATH = Path(__file__).parent.parent / "profiles.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS encounters (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        TEXT    NOT NULL,
    at             TEXT    NOT NULL,   -- ISO 8601, UTC
    lure_type      TEXT    NOT NULL,
    tactics        TEXT    NOT NULL,   -- JSON array
    channel        TEXT    NOT NULL,
    depth          TEXT    NOT NULL,
    outcome        TEXT    NOT NULL,
    score          INTEGER NOT NULL,
    recording_id   TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS encounters_by_user ON encounters (user_id, at);
"""


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def record_encounter(encounter: Encounter, db_path: Path | None = None) -> None:
    """Append one checked conversation to a user's history.

    Every analysis is recorded, not only the ones that turned out to be scams.
    Choosing to check something says what a person finds plausible, and the
    cases they caught early are the ones that show a vulnerability fading.
    """
    with closing(_connect(db_path)) as conn, conn:
        conn.execute(
            """INSERT INTO encounters
               (user_id, at, lure_type, tactics, channel, depth, outcome, score, recording_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                encounter.userId,
                encounter.at.astimezone(timezone.utc).isoformat(),
                encounter.lureType.value,
                json.dumps([t.value for t in encounter.pressureTactics]),
                encounter.channel.value,
                encounter.engagementDepth.value,
                encounter.outcome,
                encounter.score,
                encounter.recordingId,
            ),
        )


def load_encounters(user_id: str, db_path: Path | None = None) -> list[Encounter]:
    with closing(_connect(db_path)) as conn:
        rows = conn.execute(
            "SELECT * FROM encounters WHERE user_id = ? ORDER BY at", (user_id,)
        ).fetchall()

    return [
        Encounter(
            userId=r["user_id"],
            at=datetime.fromisoformat(r["at"]),
            lureType=_coerce(LureType, r["lure_type"], _RENAMED_LURES),
            pressureTactics=tuple(
                _coerce(PressureTactic, t) for t in json.loads(r["tactics"])
            ),
            channel=_coerce(Channel, r["channel"]),
            engagementDepth=_coerce(EngagementDepth, r["depth"]),
            outcome=r["outcome"],
            score=r["score"],
            recordingId=r["recording_id"],
        )
        for r in rows
    ]


def clear_encounters(user_id: str, db_path: Path | None = None) -> int:
    """Delete a user's history. Returns how many rows went.

    Exists for the sample-data affordance: loading fabricated encounters is only
    safe if they can be taken away again.
    """
    with closing(_connect(db_path)) as conn, conn:
        cursor = conn.execute("DELETE FROM encounters WHERE user_id = ?", (user_id,))
        return cursor.rowcount


def get_profile(
    user_id: str, now: datetime | None = None, db_path: Path | None = None
) -> Profile:
    return build_profile(user_id, load_encounters(user_id, db_path), now=now)
