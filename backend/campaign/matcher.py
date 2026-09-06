"""Deciding who gets warned, and — mostly — who does not.

This is the part of Sentry that acts without being asked, so it is the part that
most needs to be explainable. Every decision here is arithmetic over counts the
user can see on their own profile screen: no model is consulted about who to
interrupt.

The design has one gate and one ranking, deliberately separated:

  The gate is a fact. Has this person actually been approached with this kind of
  scam before? If not, they are not warned. Warning someone about a scam type
  they have never encountered is the noise Rule 6 is about - "warning about
  everything is how warnings stop being read" - and no score should be able to
  override it.

  The ranking is a preference. When several campaigns match and the weekly quota
  will not cover them all, the score decides which one is sent. It orders
  competing warnings; it never creates one.

Keeping those separate means the only threshold in the system is "at least
once", which is a fact rather than a number somebody chose.
"""

from __future__ import annotations

from profile.model import Profile

from .model import Campaign, Match, Severity

# How many warnings one person may receive in a rolling week. Silence is a
# feature: the cap is what stops a busy month of advisories from turning into a
# stream nobody reads.
WEEKLY_WARNING_QUOTA = 2

# Ranking weights. These only order campaigns that have already passed the gate,
# so getting them wrong changes which warning arrives first, never whether an
# unrelated one arrives at all.
POINTS_PER_LURE_ENCOUNTER = 2
POINTS_PER_SHARED_TACTIC = 1
POINTS_FOR_USUAL_CHANNEL = 1


def evaluate(campaign: Campaign, profile: Profile) -> Match:
    """Should this person be told about this campaign, and how strongly.

    Pure: the same campaign and profile always produce the same Match, so a
    warning someone disputes can be reproduced exactly.
    """
    lure = campaign.lureType.value
    seen = profile.vulnerability.get(lure, 0)

    if seen < 1:
        return Match(
            campaignId=campaign.id,
            userId=profile.userId,
            matched=False,
            score=0,
            reason=f"has never been approached with a {lure.replace('_', ' ')} scam",
        )

    shared = [t.value for t in campaign.tactics if profile.tacticSensitivity.get(t.value)]
    usual = campaign.channel.value == profile.usual_channel()

    score = (
        seen * POINTS_PER_LURE_ENCOUNTER
        + len(shared) * POINTS_PER_SHARED_TACTIC
        + (POINTS_FOR_USUAL_CHANNEL if usual else 0)
    )

    times = "once" if seen == 1 else f"{seen} times"
    reason = f"approached with a {lure.replace('_', ' ')} scam {times} before"
    if shared:
        reason += f", using {' and '.join(shared)}"
    if usual:
        reason += f", usually on {campaign.channel.value}"

    return Match(
        campaignId=campaign.id,
        userId=profile.userId,
        matched=True,
        score=score,
        reason=reason,
        detail={"lureEncounters": seen, "sharedTactics": len(shared), "usualChannel": int(usual)},
    )


def select_for_user(
    campaigns: list[Campaign],
    profile: Profile,
    already_sent: set[str],
    sent_this_week: int,
) -> list[Match]:
    """Which of these campaigns this person should actually be sent, now.

    Applies, in order: the gate, then "not already sent", then the quota. A
    campaign is only ever sent to someone once - not repeated because they did
    not open it.
    """
    matches = [
        m
        for c in campaigns
        if c.approved and c.is_active() and c.id not in already_sent
        if (m := evaluate(c, profile)).matched
    ]

    # Highest severity first, then strongest match. Severity leads so that a
    # HIGH campaign takes the last slot from a NORMAL one rather than losing it
    # to a profile that happens to score higher.
    by_id = {c.id: c for c in campaigns}
    matches.sort(
        key=lambda m: (by_id[m.campaignId].severity is Severity.HIGH, m.score),
        reverse=True,
    )

    remaining = max(0, WEEKLY_WARNING_QUOTA - sent_this_week)
    return matches[:remaining]
