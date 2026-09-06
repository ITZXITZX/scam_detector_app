"""Persistence for campaigns.

One table. The server holds the news and nothing about who was told: no record
of which person received which warning, and no consent flag. The phone decides
what it has already shown and how many it has raised this week, because that
is the only place that needs to know.

The matcher still takes `already_sent` and `sent_this_week`, so those can be
supplied by the device without the server storing them.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import date
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


SEED_PATH = Path(__file__).parent / "seed_advisories.json"


def seed_campaigns(db_path: Path | None = None) -> int:
    """Fill an empty store with the advisories in `seed_advisories.json`.

    The database is not in version control, so a fresh checkout has an empty
    feed until someone runs the scraper — which needs an API key and a working
    police.gov.sg. That is a bad first run for anyone opening the app to look
    at it, so five real advisories ship with the code instead.

    They are real: the text was drafted from the linked advisory by the same
    ingest path, read by a person, and frozen here. Only the dates differ from
    a scraped campaign — a seeded one carries the advisory's own publication
    date and no expiry, so a demo does not go blank a month from now.

    Only ever runs against an empty table: it must not resurrect a campaign
    someone deliberately removed, or overwrite an edited one.
    """
    with closing(_connect(db_path)) as conn:
        if conn.execute("SELECT 1 FROM campaigns LIMIT 1").fetchone():
            return 0

    if not SEED_PATH.exists():
        return 0

    seeded = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    for raw in seeded:
        save_campaign(
            Campaign(
                id=raw["id"],
                title=raw["title"],
                body=raw["body"],
                lureType=LureType(raw["lureType"]),
                tactics=tuple(PressureTactic(t) for t in raw.get("tactics", [])),
                channel=Channel(raw.get("channel", Channel.UNKNOWN.value)),
                claimedIdentity=ClaimedIdentity(
                    raw.get("claimedIdentity", ClaimedIdentity.NONE.value)
                ),
                severity=Severity(raw.get("severity", Severity.NORMAL.value)),
                activeFrom=date.fromisoformat(raw["publishedOn"]),
                activeUntil=None,
                source=raw.get("source", ""),
                approved=True,
            ),
            db_path=db_path,
        )
    return len(seeded)
