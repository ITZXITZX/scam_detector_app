"""Watch Sentry scrape today's police advisories and decide who to warn.

    .venv\\Scripts\\python.exe demo_warnings.py

Scrapes the Singapore Police Force news index live, has Claude write each
advisory up as a campaign, and shows which of five example people would be
notified. Nothing is hardcoded: the advisories are whatever is on the site now.

Needs ANTHROPIC_API_KEY in backend/.env for the drafting step. Without it the
scraping still runs and the drafting is skipped.
"""

from __future__ import annotations

import sys
import textwrap
from datetime import datetime, timedelta, timezone

from campaign.ingest import draft_campaign, fetch_advisories, fetch_article
from campaign.matcher import evaluate
from campaign.store import save_campaign
from pattern.taxonomy import Channel, EngagementDepth, LureType, PressureTactic
from profile.model import Encounter, build_profile

MODEL = "claude-haiku-4-5"
NOW = datetime.now(timezone.utc)


def _person(name, lure, times, channel=Channel.IMESSAGE, tactics=(PressureTactic.URGENCY,)):
    """An example profile: someone who has checked this kind of scam N times."""
    return name, build_profile(
        name,
        [
            Encounter(
                userId=name,
                at=NOW - timedelta(days=4 * (i + 1)),
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


PEOPLE = [
    _person("Ah Ma", LureType.PHISHING, 3),
    _person("Wei", LureType.PHISHING, 1, Channel.WHATSAPP),
    _person("Siti", LureType.INVESTMENT, 2),
    _person("Raj", LureType.SEXUAL_SERVICE, 1, Channel.TELEGRAM),
    ("New user", build_profile("New user", [], now=NOW)),
]


def main(save: bool = False) -> None:
    print("\nSTEP 1  scraping police.gov.sg news index\n")
    advisories = fetch_advisories(limit=5)
    if not advisories:
        print("  no scam advisories found on the index right now")
        return
    for a in advisories:
        print(f"  {a.published}  {a.title}")

    for advisory in advisories:
        print("\n" + "=" * 88)
        print(f"STEP 2  reading: {advisory.title}")
        try:
            article = fetch_article(advisory.url)
        except Exception as exc:
            print(f"  could not read it: {exc}")
            continue
        print(f"  {len(article)} characters")

        print("\nSTEP 3  drafting a campaign (Claude labels it; it decides nothing)")
        campaign = draft_campaign(advisory, article, MODEL)
        if campaign is None:
            print("  drafting unavailable - is ANTHROPIC_API_KEY set in backend/.env?")
            continue

        print(f"  lure      {campaign.lureType.value}")
        print(f"  channel   {campaign.channel.value}")
        print(f"  identity  {campaign.claimedIdentity.value}")
        print(f"  tactics   {', '.join(t.value for t in campaign.tactics) or '-'}")
        print(f"  severity  {campaign.severity.value}")
        print(f"  live      {campaign.activeFrom} to {campaign.activeUntil}")
        print(f"  approved  {campaign.approved}   (drafts are never sent)")

        print("\n  the notification, as it would appear:")
        print("  +" + "-" * 72)
        print(f"  | {campaign.title}")
        for line in textwrap.wrap(campaign.body, 68):
            print(f"  | {line}")
        print("  +" + "-" * 72)

        print("\nSTEP 4  who would be warned")
        for name, profile in PEOPLE:
            match = evaluate(campaign, profile)
            print(f"  [{'NOTIFY' if match.matched else '  --  '}] {name:<10} {match.reason}")

        if save:
            save_campaign(campaign)
            print(f"\n  saved as a draft: {campaign.id}")


if __name__ == "__main__":
    main(save="--save" in sys.argv)
