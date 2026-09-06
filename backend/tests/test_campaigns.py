"""Tests for campaign matching.

This is the part of Sentry that interrupts people without being asked, so most
of what is worth asserting is that it stays quiet: someone who has never met
this kind of scam, someone who has already been told, someone over quota,
someone who paused.

A warning that should not have been sent cannot be taken back.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from campaign.matcher import WEEKLY_WARNING_QUOTA, evaluate, select_for_user  # noqa: E402
from campaign.model import Campaign, Severity  # noqa: E402
from campaign.store import (  # noqa: E402
    approve_campaign,
    load_campaigns,
    save_campaign,
)
from pattern.taxonomy import (  # noqa: E402
    Channel,
    ClaimedIdentity,
    EngagementDepth,
    LureType,
    PressureTactic,
)
from profile.model import Encounter, build_profile  # noqa: E402

NOW = datetime(2026, 9, 6, tzinfo=timezone.utc)


def campaign(
    *,
    id: str = "c1",
    lure: LureType = LureType.PHISHING,
    tactics: tuple[PressureTactic, ...] = (PressureTactic.URGENCY,),
    channel: Channel = Channel.IMESSAGE,
    severity: Severity = Severity.NORMAL,
    approved: bool = True,
    active_from: date | None = None,
    active_until: date | None = None,
) -> Campaign:
    return Campaign(
        id=id,
        title="Fake DBS and Shopee messages on iMessage",
        body=(
            "People are getting iMessages about a pending transaction, with a "
            "number to call. The hotline asks for card details and your OTP. "
            "DBS never asks for your OTP."
        ),
        lureType=lure,
        tactics=tactics,
        channel=channel,
        claimedIdentity=ClaimedIdentity.BANK,
        severity=severity,
        activeFrom=active_from,
        activeUntil=active_until,
        source="https://www.police.gov.sg/Media-Hub/News/2026/09/…",
        approved=approved,
    )


def profile_with(
    *,
    lure: LureType = LureType.PHISHING,
    times: int = 1,
    tactics: tuple[PressureTactic, ...] = (PressureTactic.URGENCY,),
    channel: Channel = Channel.IMESSAGE,
    user: str = "u1",
):
    return build_profile(
        user,
        [
            Encounter(
                userId=user,
                at=NOW - timedelta(days=3 * (i + 1)),
                lureType=lure,
                pressureTactics=tactics,
                channel=channel,
                engagementDepth=EngagementDepth.REPLIED,
                outcome="SCAM",
                score=90,
            )
            for i in range(times)
        ],
        now=NOW,
    )


# --------------------------------------------------------------------------
# The gate: has this actually happened to them
# --------------------------------------------------------------------------


def test_someone_targeted_this_way_before_is_matched():
    match = evaluate(campaign(), profile_with())
    assert match.matched
    assert "phishing scam once before" in match.reason


def test_someone_who_has_never_met_this_scam_is_not_warned():
    """The gate is a fact, not a threshold.

    Warning someone about a scam type they have never encountered is the noise
    Rule 6 is about, and no score is allowed to override it.
    """
    match = evaluate(campaign(lure=LureType.LOAN), profile_with(lure=LureType.PHISHING))
    assert not match.matched
    assert match.score == 0
    assert "never been approached" in match.reason


def test_a_brand_new_user_is_warned_about_nothing():
    empty = build_profile("new", [], now=NOW)
    assert not evaluate(campaign(), empty).matched


def test_the_match_explains_itself():
    """Someone who asks why their phone buzzed has to get an answer."""
    match = evaluate(campaign(), profile_with(times=3))
    assert match.matched
    assert "3 times before" in match.reason
    assert "urgency" in match.reason
    assert match.detail["lureEncounters"] == 3


def test_matching_is_reproducible():
    c, p = campaign(), profile_with(times=2)
    assert evaluate(c, p) == evaluate(c, p)


# --------------------------------------------------------------------------
# Ranking: only ever decides order, never whether
# --------------------------------------------------------------------------


def test_more_encounters_rank_higher():
    once = evaluate(campaign(), profile_with(times=1)).score
    thrice = evaluate(campaign(), profile_with(times=3)).score
    assert thrice > once


def test_a_shared_tactic_and_usual_channel_rank_higher():
    bare = evaluate(
        campaign(tactics=(), channel=Channel.WHATSAPP),
        profile_with(channel=Channel.IMESSAGE),
    ).score
    rich = evaluate(campaign(), profile_with()).score
    assert rich > bare


# --------------------------------------------------------------------------
# Silence: the quota, repeats, drafts and expiry
# --------------------------------------------------------------------------


def test_the_weekly_quota_caps_how_many_are_sent():
    campaigns = [campaign(id=f"c{i}") for i in range(5)]
    chosen = select_for_user(campaigns, profile_with(), already_sent=set(), sent_this_week=0)
    assert len(chosen) == WEEKLY_WARNING_QUOTA


def test_nothing_is_sent_once_the_quota_is_spent():
    chosen = select_for_user(
        [campaign()], profile_with(), already_sent=set(),
        sent_this_week=WEEKLY_WARNING_QUOTA,
    )
    assert chosen == []


def test_a_high_severity_campaign_takes_the_last_slot():
    """When the quota will not cover everything, severity leads the ordering so
    an urgent campaign displaces a routine one rather than losing to it."""
    campaigns = [
        campaign(id="routine", severity=Severity.NORMAL),
        campaign(id="urgent", severity=Severity.HIGH),
    ]
    chosen = select_for_user(
        campaigns, profile_with(), already_sent=set(),
        sent_this_week=WEEKLY_WARNING_QUOTA - 1,
    )
    assert [m.campaignId for m in chosen] == ["urgent"]


def test_a_campaign_is_never_sent_to_the_same_person_twice():
    """Not repeated because they did not open it."""
    chosen = select_for_user(
        [campaign(id="c1")], profile_with(), already_sent={"c1"}, sent_this_week=0
    )
    assert chosen == []


def test_an_unapproved_draft_is_never_sent():
    """Nothing reaches a phone before a person has read the text it will send."""
    chosen = select_for_user(
        [campaign(approved=False)], profile_with(), already_sent=set(), sent_this_week=0
    )
    assert chosen == []


def test_an_expired_campaign_is_not_sent():
    old = campaign(active_until=date(2026, 8, 1))
    assert not old.is_active(on=date(2026, 9, 6))
    chosen = select_for_user([old], profile_with(), already_sent=set(), sent_this_week=0)
    assert chosen == []


def test_a_campaign_that_has_not_started_is_not_sent():
    future = campaign(active_from=date(2026, 12, 1))
    assert not future.is_active(on=date(2026, 9, 6))


# --------------------------------------------------------------------------
# Persistence, consent, and the record of what went out
# --------------------------------------------------------------------------


def test_campaigns_round_trip(tmp_path):
    db = tmp_path / "c.db"
    original = campaign(active_from=date(2026, 9, 2), active_until=date(2026, 10, 2))
    save_campaign(original, db_path=db)
    loaded = load_campaigns(db_path=db)[0]
    assert loaded == original


def test_only_approved_campaigns_are_listed_when_asked(tmp_path):
    db = tmp_path / "c.db"
    save_campaign(campaign(id="draft", approved=False), db_path=db)
    save_campaign(campaign(id="live", approved=True), db_path=db)
    assert {c.id for c in load_campaigns(approved_only=True, db_path=db)} == {"live"}
    assert len(load_campaigns(db_path=db)) == 2


def test_approving_a_draft_makes_it_sendable(tmp_path):
    db = tmp_path / "c.db"
    save_campaign(campaign(id="draft", approved=False), db_path=db)
    assert approve_campaign("draft", db_path=db)
    assert load_campaigns(approved_only=True, db_path=db)[0].id == "draft"

# The server no longer records which person received which warning, nor a
# consent flag. Both were removed: the phone is the only place that needs to
# know what it has already shown, and keeping a per-person send log on the
# server means holding a list of who is vulnerable to what. `select_for_user`
# still takes `already_sent` and `sent_this_week`, so the device supplies them.


# --------------------------------------------------------------------------
# The seeded feed: what someone sees before they have scraped anything
# --------------------------------------------------------------------------


def test_a_fresh_install_has_a_feed_without_scraping_anything():
    """The database is gitignored, so a new checkout starts with nothing.

    An empty feed is indistinguishable from a broken one, and the scraper needs
    an API key and a reachable police.gov.sg to fill it.
    """
    from campaign.store import seed_campaigns

    db = Path(tempfile.mkdtemp()) / "fresh.db"
    assert load_campaigns(approved_only=True, db_path=db) == []
    assert seed_campaigns(db_path=db) == 5
    assert len(load_campaigns(approved_only=True, db_path=db)) == 5


def test_seeding_never_runs_twice():
    """It must not resurrect a campaign that was removed on purpose."""
    from campaign.store import seed_campaigns

    db = Path(tempfile.mkdtemp()) / "fresh.db"
    seed_campaigns(db_path=db)
    assert seed_campaigns(db_path=db) == 0


def test_seeded_advisories_do_not_expire_during_a_demo():
    """A scraped campaign lives 30 days; a seeded one has to still be there in
    six months, or the app goes blank with no explanation."""
    from campaign.store import seed_campaigns

    db = Path(tempfile.mkdtemp()) / "fresh.db"
    seed_campaigns(db_path=db)
    for c in load_campaigns(approved_only=True, db_path=db):
        assert c.activeUntil is None
        assert c.is_active(on=date(2027, 12, 31))


def test_seeded_advisories_are_dated_by_the_advisory_not_the_scrape():
    """The card prints this date next to "Singapore Police Force"; a scrape
    date there would attribute the wrong day to a real advisory."""
    from campaign.store import seed_campaigns

    db = Path(tempfile.mkdtemp()) / "fresh.db"
    seed_campaigns(db_path=db)
    for c in load_campaigns(approved_only=True, db_path=db):
        stamp = c.activeFrom.strftime("%Y%m%d")
        assert stamp in c.source.replace("-", ""), c.source


def test_a_seeded_advisory_still_matches_a_profile():
    """Seeding is only worth doing if the cards behave like scraped ones."""
    from campaign.store import seed_campaigns

    db = Path(tempfile.mkdtemp()) / "fresh.db"
    seed_campaigns(db_path=db)
    phishing = [
        c
        for c in load_campaigns(approved_only=True, db_path=db)
        if c.lureType is LureType.PHISHING
    ]
    assert phishing
    assert evaluate(phishing[0], profile_with(lure=LureType.PHISHING)).matched
    assert not evaluate(phishing[0], build_profile("new", [], now=NOW)).matched
