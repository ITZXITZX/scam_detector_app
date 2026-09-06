"""Sample encounters, for looking at the profile screen without months of use.

The screen is meant to show a spread of scam types and a habitual channel.
Real testing produces neither: every analysis is the same sample recording, and
the channel comes back "unknown", so that section never renders.

Everything here is fabricated. It is a development aid, not seed data for a real
account, and the endpoint that calls it should not ship in a release build.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from pattern.taxonomy import Channel, EngagementDepth, LureType, PressureTactic

from .model import Encounter
from .store import record_encounter

# Shaped to exercise the screen: one lure clearly on top, one mid, one nearly
# faded, a channel habit, and a range of depths so the weighting is visible.
_SAMPLE = [
    # (days ago, lure, depth, tactics, channel)
    (2, LureType.AUTHORITY, EngagementDepth.SHARED_PERSONAL_INFO,
     (PressureTactic.URGENCY, PressureTactic.ISOLATION), Channel.WHATSAPP),
    (11, LureType.AUTHORITY, EngagementDepth.REPLIED,
     (PressureTactic.URGENCY, PressureTactic.THREAT), Channel.WHATSAPP),
    (34, LureType.AUTHORITY, EngagementDepth.NO_REPLY,
     (PressureTactic.AUTHORITY_CLAIM,), Channel.SMS),
    (19, LureType.INVESTMENT, EngagementDepth.INITIATED_PAYMENT,
     (PressureTactic.URGENCY, PressureTactic.FLATTERY), Channel.TELEGRAM),
    (63, LureType.INVESTMENT, EngagementDepth.REPLIED,
     (PressureTactic.FLATTERY,), Channel.WHATSAPP),
    # An old one, so the list is not all from the last month.
    (240, LureType.PHISHING, EngagementDepth.NO_REPLY,
     (PressureTactic.URGENCY,), Channel.SMS),
]


def load_sample_profile(user_id: str, db_path: Path | None = None) -> int:
    """Insert the sample encounters for `user_id`. Returns how many were added."""
    now = datetime.now(timezone.utc)
    for days_ago, lure, depth, tactics, channel in _SAMPLE:
        record_encounter(
            Encounter(
                userId=user_id,
                at=now - timedelta(days=days_ago),
                lureType=lure,
                pressureTactics=tactics,
                channel=channel,
                engagementDepth=depth,
                outcome="SCAM" if depth is not EngagementDepth.NO_REPLY else "COULDNT_CONFIRM",
                score=100 if depth is not EngagementDepth.NO_REPLY else 35,
                recordingId="sample",
            ),
            db_path=db_path,
        )
    return len(_SAMPLE)
