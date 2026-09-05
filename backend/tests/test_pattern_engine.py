"""Tests for the pattern engine.

No API key, no network, no emulator. These run in about a second, which is the
point of moving the verdict out of the model and into Python: the system can now
be evaluated without spending money.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pattern.domains import (  # noqa: E402
    impersonated_brand,
    is_allowlisted,
    near_miss_domain,
    registrable_domain,
)
from pattern.scoring import Outcome, decide  # noqa: E402
from pattern.taxonomy import (  # noqa: E402
    ClaimedIdentity,
    LureType,
    PressureTactic,
    RequestedAction,
    Signals,
)

# --------------------------------------------------------------------------
# Who owns this link?
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://mas-verify.sg-alert.test/case/114872", "sg-alert.test"),
        ("https://www.police.gov.sg/advisories", "police.gov.sg"),
        ("https://internet-banking.dbs.com.sg/login", "dbs.com.sg"),
        # Everything left of the registrable domain is attacker-controlled.
        ("https://dbs.com.sg.secure-login.co/login", "secure-login.co"),
        ("not a url", None),
        ("", None),
    ],
)
def test_registrable_domain(url, expected):
    assert registrable_domain(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://www.mas.gov.sg/news",
        "https://www.police.gov.sg/advisories",
        "https://www.dbs.com.sg/personal",
        "https://internet-banking.dbs.com.sg/login",
    ],
)
def test_genuine_links_are_allowlisted(url):
    assert is_allowlisted(url)


@pytest.mark.parametrize(
    "url",
    ["https://mas-verify.sg-alert.test/x", "https://dbs.com.sg.secure-login.co/login"],
)
def test_impersonating_links_are_not_allowlisted(url):
    assert not is_allowlisted(url)


# --------------------------------------------------------------------------
# Lookalike detection, and the false positives it must avoid
# --------------------------------------------------------------------------


def test_brand_in_subdomain_is_impersonation():
    assert impersonated_brand("https://mas-verify.sg-alert.test/case/1") == (
        "mas",
        "sg-alert.test",
    )


def test_real_brand_domain_is_not_impersonation():
    assert impersonated_brand("https://www.mas.gov.sg/news") is None


@pytest.mark.parametrize(
    "url",
    [
        "https://christmas-deals.com/sale",   # contains "mas" as a substring
        "https://masterclass.com/courses",    # contains "mas" as a substring
        "https://mastodon.social/@someone",
    ],
)
def test_ordinary_words_containing_a_brand_are_not_flagged(url):
    """Whole-token matching, not substring matching.

    Substring matching would flag Christmas as the Monetary Authority of
    Singapore. A false SCAM verdict is expensive: it teaches people to ignore
    the true ones.
    """
    assert impersonated_brand(url) is None


def test_typosquat_is_a_near_miss():
    assert near_miss_domain("https://0cbc.com/login") == "ocbc.com"


def test_genuine_domain_is_not_a_near_miss():
    assert near_miss_domain("https://ocbc.com/login") is None


# --------------------------------------------------------------------------
# Verdicts
# --------------------------------------------------------------------------


def _fired(verdict) -> set[str]:
    return {c.id for c in verdict.checks if c.fired}


def test_authority_claim_with_unofficial_link_is_a_hard_trigger():
    """The shape of the test conversation: fake police officer, fake MAS link."""
    verdict = decide(
        Signals(
            lureType=LureType.AUTHORITY,
            claimedIdentity=ClaimedIdentity.POLICE,
            requestedAction=RequestedAction.TRANSFER_MONEY,
            pressureTactics=(
                PressureTactic.URGENCY,
                PressureTactic.SECRECY,
                PressureTactic.ISOLATION,
            ),
            urls=("https://mas-verify.sg-alert.test/case/114872",),
        )
    )
    assert verdict.outcome is Outcome.SCAM
    assert "C2" in verdict.hardTriggered
    assert {"C2", "C3", "C5", "C7"} <= _fired(verdict)
    assert verdict.reasons  # a verdict must be able to explain itself


def test_verdict_is_reproducible():
    """Same signals, same verdict. This is the property the model could not give."""
    signals = Signals(
        lureType=LureType.AUTHORITY,
        claimedIdentity=ClaimedIdentity.BANK,
        requestedAction=RequestedAction.SHARE_OTP,
        urls=("https://dbs.com.sg.secure-login.co/login",),
    )
    assert decide(signals) == decide(signals)


def test_otp_request_alone_is_not_enough_to_call_it_a_scam():
    """C4 scores 40, below the threshold. Something asking for an OTP with no
    other signal is suspicious but not proven, and the honest answer is
    "couldn't confirm" rather than a guess in either direction."""
    verdict = decide(Signals(requestedAction=RequestedAction.SHARE_OTP))
    assert "C4" in _fired(verdict)
    assert verdict.outcome is Outcome.COULDNT_CONFIRM


def test_benign_conversation_is_never_called_safe():
    """Rule 1: there is no "this is safe" outcome, only SCAM or COULDN'T CONFIRM."""
    verdict = decide(Signals())
    assert verdict.outcome is Outcome.COULDNT_CONFIRM
    assert verdict.score == 0
    assert not verdict.reasons
    assert Outcome.SCAM.value != "SAFE"
    assert not hasattr(Outcome, "SAFE")


def test_genuine_bank_link_does_not_fire_domain_checks():
    """A real bank telling you to log in is not, by itself, a scam."""
    verdict = decide(
        Signals(
            claimedIdentity=ClaimedIdentity.BANK,
            urls=("https://internet-banking.dbs.com.sg/login",),
        )
    )
    assert not ({"C1", "C2", "C3"} & _fired(verdict))
    assert verdict.outcome is Outcome.COULDNT_CONFIRM
