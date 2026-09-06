"""Persistence for campaigns, consent, and what has already been sent.

Three tables, in the same SQLite file as the profile so a warning can be decided
in one place without a join across databases.

Consent lives here rather than on the device because Rule 5 requires it to be
checked when a warning is *sent*, not when it is scheduled. Someone who pauses
on Tuesday must not receive a warning matched on Monday for Wednesday, and a
setting that only exists on the phone cannot stop the server sending it.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from pattern.taxonomy import Channel, ClaimedIdentity, LureType, PressureTactic

from .model import Campaign, Severity

DB_PATH = Path(__file__).parent.parent / "profiles.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS campaigns (
    id                TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    body              TEXT NOT NULL,
    lure_type         TEXT NOT NULL,
    tactics           TEXT NOT NULL,   -- JSON array
    channel           TEXT NOT NULL,
    claimed_identity  TEXT NOT NULL,
    severity          TEXT NOT NULL,
    active_from       TEXT,            -- ISO date
    active_until      TEXT,
    source            TEXT NOT NULL DEFAULT '',
    approved          INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS warnings_sent (
    user_id      TEXT NOT NULL,
    campaign_id  TEXT NOT NULL,
    at           TEXT NOT NULL,
    PRIMARY KEY (user_id, campaign_id)
);

CREATE TABLE IF NOT EXISTS consent (
    user_id  TEXT PRIMARY KEY,
    paused   INTEGER NOT NULL DEFAULT 0,
    at       TEXT NOT NULL
);
"""


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _to_campaign(r: sqlite3.Row) -> Campaign:
    return Campaign(
        id=r["id"],
        title=r["title"],
        body=r["body"],
        lureType=LureType(r["lure_type"]),
        tactics=tuple(PressureTactic(t) for t in json.loads(r["tactics"])),
        channel=Channel(r["channel"]),
        claimedIdentity=ClaimedIdentity(r["claimed_identity"]),
        severity=Severity(r["severity"]),
        activeFrom=date.fromisoformat(r["active_from"]) if r["active_from"] else None,
        activeUntil=date.fromisoformat(r["active_until"]) if r["active_until"] else None,
        source=r["source"],
        approved=bool(r["approved"]),
    )


def save_campaign(campaign: Campaign, db_path: Path | None = None) -> None:
    """Insert or replace a campaign.

    Drafts arrive unapproved. Nothing unapproved is ever matched, so a draft can
    sit in the store safely until a person has read the text it would send.
    """
    with closing(_connect(db_path)) as conn, conn:
        conn.execute(
            """INSERT OR REPLACE INTO campaigns
               (id, title, body, lure_type, tactics, channel, claimed_identity,
                severity, active_from, active_until, source, approved)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                campaign.id,
                campaign.title,
                campaign.body,
                campaign.lureType.value,
                json.dumps([t.value for t in campaign.tactics]),
                campaign.channel.value,
                campaign.claimedIdentity.value,
                campaign.severity.value,
                campaign.activeFrom.isoformat() if campaign.activeFrom else None,
                campaign.activeUntil.isoformat() if campaign.activeUntil else None,
                campaign.source,
                int(campaign.approved),
            ),
        )


def load_campaigns(
    approved_only: bool = False, db_path: Path | None = None
) -> list[Campaign]:
    query = "SELECT * FROM campaigns"
    if approved_only:
        query += " WHERE approved = 1"
    with closing(_connect(db_path)) as conn:
        return [_to_campaign(r) for r in conn.execute(query).fetchall()]


def approve_campaign(campaign_id: str, db_path: Path | None = None) -> bool:
    """Mark a campaign as read by a person and cleared to send."""
    with closing(_connect(db_path)) as conn, conn:
        cur = conn.execute(
            "UPDATE campaigns SET approved = 1 WHERE id = ?", (campaign_id,)
        )
        return cur.rowcount > 0


# --------------------------------------------------------------------------
# Consent
# --------------------------------------------------------------------------


def set_paused(user_id: str, paused: bool, db_path: Path | None = None) -> None:
    with closing(_connect(db_path)) as conn, conn:
        conn.execute(
            "INSERT OR REPLACE INTO consent (user_id, paused, at) VALUES (?, ?, ?)",
            (user_id, int(paused), datetime.now(timezone.utc).isoformat()),
        )


def is_paused(user_id: str, db_path: Path | None = None) -> bool:
    with closing(_connect(db_path)) as conn:
        row = conn.execute(
            "SELECT paused FROM consent WHERE user_id = ?", (user_id,)
        ).fetchone()
    return bool(row["paused"]) if row else False


# --------------------------------------------------------------------------
# What has already gone out
# --------------------------------------------------------------------------


def record_warning(user_id: str, campaign_id: str, db_path: Path | None = None) -> None:
    with closing(_connect(db_path)) as conn, conn:
        conn.execute(
            """INSERT OR IGNORE INTO warnings_sent (user_id, campaign_id, at)
               VALUES (?, ?, ?)""",
            (user_id, campaign_id, datetime.now(timezone.utc).isoformat()),
        )


def campaigns_already_sent(user_id: str, db_path: Path | None = None) -> set[str]:
    with closing(_connect(db_path)) as conn:
        rows = conn.execute(
            "SELECT campaign_id FROM warnings_sent WHERE user_id = ?", (user_id,)
        ).fetchall()
    return {r["campaign_id"] for r in rows}


def warnings_sent_since(
    user_id: str, since: datetime, db_path: Path | None = None
) -> int:
    with closing(_connect(db_path)) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM warnings_sent WHERE user_id = ? AND at >= ?",
            (user_id, since.isoformat()),
        ).fetchone()
    return int(row["n"])


def warnings_sent_this_week(
    user_id: str, now: datetime | None = None, db_path: Path | None = None
) -> int:
    """A rolling seven days, not a calendar week.

    A calendar week would let two warnings land on Sunday night and two more on
    Monday morning, which is four in twelve hours and exactly the flood the
    quota exists to prevent.
    """
    now = now or datetime.now(timezone.utc)
    return warnings_sent_since(user_id, now - timedelta(days=7), db_path)
