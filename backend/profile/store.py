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
            lureType=LureType(r["lure_type"]),
            pressureTactics=tuple(PressureTactic(t) for t in json.loads(r["tactics"])),
            channel=Channel(r["channel"]),
            engagementDepth=EngagementDepth(r["depth"]),
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
