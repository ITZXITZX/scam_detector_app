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
    Channel,
    ClaimedIdentity,
    LureType,
    ModelSuspicion,
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
            requestedActions=(RequestedAction.CLICK_LINK, RequestedAction.TRANSFER_MONEY),
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
        requestedActions=(RequestedAction.SHARE_OTP,),
        urls=("https://dbs.com.sg.secure-login.co/login",),
    )
    assert decide(signals) == decide(signals)


def test_otp_request_alone_is_not_enough_to_call_it_a_scam():
    """C4 scores 40, below the threshold. Something asking for an OTP with no
    other signal is suspicious but not proven, and the honest answer is
    "couldn't confirm" rather than a guess in either direction."""
    verdict = decide(Signals(requestedActions=(RequestedAction.SHARE_OTP,)))
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


def test_payment_check_survives_a_conversation_asking_for_several_things():
    """Regression: requestedAction used to be a single value.

    Scams ask for things in sequence - open this link, confirm your NRIC, then
    transfer the money - so forcing one label meant every check reading that
    field could only see whichever the model judged most important. A check that
    quietly fails to fire is worse than one that is absent: the score still
    looks as though the case was considered.
    """
    verdict = decide(
        Signals(
            claimedIdentity=ClaimedIdentity.POLICE,
            requestedActions=(
                RequestedAction.CLICK_LINK,
                RequestedAction.SHARE_ID_DOCUMENT,
                RequestedAction.TRANSFER_MONEY,
            ),
        )
    )
    assert "C5" in _fired(verdict)


def test_credential_check_reports_every_credential_asked_for():
    verdict = decide(
        Signals(
            requestedActions=(
                RequestedAction.SHARE_OTP,
                RequestedAction.SHARE_CREDENTIALS,
            )
        )
    )
    detail = next(c.detail for c in verdict.checks if c.id == "C4")
    assert "share otp" in detail and "share credentials" in detail


# --------------------------------------------------------------------------
# C11 - the model's structural read
# --------------------------------------------------------------------------


def test_model_suspicion_alone_cannot_decide_a_verdict():
    """50 points, threshold 60. The cap is the whole design.

    A model that misreads a legitimate conversation must not be able to call it
    a scam unaided. It can push something over the line alongside other
    evidence; it cannot supply all of the evidence itself.
    """
    verdict = decide(
        Signals(
            modelSuspicion=ModelSuspicion.STRONG,
            modelSuspicionReason="Says he is your agent, then asks your name",
        )
    )
    assert "C11" in _fired(verdict)
    assert verdict.score < 60
    assert verdict.outcome is Outcome.COULDNT_CONFIRM


def test_model_suspicion_tips_a_conversation_the_checks_score_low():
    """The advance-fee case: no link, so every structural check is blind.

    Lure plus one tactic scores 15 on its own, which reads as almost safe for a
    conversation that is plainly a scam. This is the gap C11 exists to cover.
    """
    without = decide(
        Signals(
            lureType=LureType.OTHER,
            pressureTactics=(PressureTactic.URGENCY,),
            claimedIdentity=ClaimedIdentity.STRANGER,
        )
    )
    assert without.score == 15
    assert without.outcome is Outcome.COULDNT_CONFIRM

    with_model = decide(
        Signals(
            lureType=LureType.OTHER,
            pressureTactics=(PressureTactic.URGENCY,),
            claimedIdentity=ClaimedIdentity.STRANGER,
            modelSuspicion=ModelSuspicion.STRONG,
            modelSuspicionReason="Offers a cash delivery you never asked for",
        )
    )
    assert with_model.outcome is Outcome.SCAM


def test_model_suspicion_cannot_lower_a_verdict():
    """Escalate-only. A fired domain check stands whatever the model thinks.

    Rule 1's asymmetry: a false alarm is an annoyance, a false reassurance is
    the mistake that costs someone their savings.
    """
    signals = dict(
        claimedIdentity=ClaimedIdentity.POLICE,
        urls=("https://mas-verify.sg-alert.test/case/1",),
    )
    assert decide(Signals(**signals)).outcome is Outcome.SCAM
    assert (
        decide(Signals(**signals, modelSuspicion=ModelSuspicion.NONE)).outcome
        is Outcome.SCAM
    )


def test_model_suspicion_reason_is_surfaced():
    """A fired check has to say what it saw, or the verdict cannot explain itself."""
    verdict = decide(
        Signals(
            modelSuspicion=ModelSuspicion.MODERATE,
            modelSuspicionReason="Asks for payment in gift cards",
        )
    )
    assert "Asks for payment in gift cards" in verdict.reasons


def test_model_suspicion_without_a_reason_still_says_something():
    verdict = decide(Signals(modelSuspicion=ModelSuspicion.STRONG))
    assert "C11" in _fired(verdict)
    assert verdict.reasons  # never an empty explanation


# --------------------------------------------------------------------------
# Checks derived from ScamShield's published rules
#
# These weights are not fitted to a screenshot. Each rests on a line ScamShield
# publishes, quoted in the check's docstring, and where their wording is
# categorical the check decides the verdict alone.
# --------------------------------------------------------------------------


def test_bank_link_over_sms_fires():
    """ScamShield: "Banks will never send you any clickable links via SMS"."""
    verdict = decide(
        Signals(
            claimedIdentity=ClaimedIdentity.BANK,
            channel=Channel.SMS,
            urls=("https://dbs-secure.example.test/verify",),
        )
    )
    assert "C12" in _fired(verdict)


def test_bank_link_in_a_chat_app_does_not_fire_the_sms_rule():
    """The rule is about SMS specifically, so the check has to be too."""
    verdict = decide(
        Signals(
            claimedIdentity=ClaimedIdentity.BANK,
            channel=Channel.WHATSAPP,
            urls=("https://dbs-secure.example.test/verify",),
        )
    )
    assert "C12" not in _fired(verdict)


def test_unsolicited_loan_offer_decides_the_verdict():
    """ScamShield: "Any unsolicited loan offer is a scam".

    Licensed moneylenders are prohibited from advertising, so an approach
    offering a loan is either unlicensed or a scammer. Categorical in the
    source, so categorical here.
    """
    verdict = decide(Signals(lureType=LureType.LOAN, unsolicitedContact=True))
    assert verdict.outcome is Outcome.SCAM
    assert "C13" in verdict.hardTriggered


def test_a_loan_the_user_went_looking_for_is_not_the_same_thing():
    """The rule turns on the offer being unsolicited. Someone who searched for a
    loan and is talking to a lender has not met that condition."""
    verdict = decide(Signals(lureType=LureType.LOAN, unsolicitedContact=False))
    assert "C13" not in _fired(verdict)
    assert verdict.outcome is Outcome.COULDNT_CONFIRM


def test_remote_access_from_an_unsolicited_caller_decides_the_verdict():
    """ScamShield: "Never download remote access applications at the request of
    an unsolicited caller, as this gives them full control of your device"."""
    verdict = decide(
        Signals(
            lureType=LureType.TECH_SUPPORT,
            requestedActions=(RequestedAction.INSTALL_REMOTE_ACCESS,),
            unsolicitedContact=True,
        )
    )
    assert verdict.outcome is Outcome.SCAM
    assert "C14" in verdict.hardTriggered


def test_remote_access_the_user_asked_for_is_not_flagged():
    """Support the user called themselves is the case the rule excludes."""
    verdict = decide(
        Signals(
            lureType=LureType.TECH_SUPPORT,
            requestedActions=(RequestedAction.INSTALL_REMOTE_ACCESS,),
            unsolicitedContact=False,
        )
    )
    assert "C14" not in _fired(verdict)


def test_job_asking_for_money_first_fires():
    """ScamShield lists "pay upfront before starting the job" as a scam sign."""
    verdict = decide(
        Signals(
            lureType=LureType.JOB,
            requestedActions=(RequestedAction.PAY_UPFRONT_FEE,),
        )
    )
    assert "C15" in _fired(verdict)


def test_an_ordinary_job_offer_does_not_fire():
    verdict = decide(Signals(lureType=LureType.JOB))
    assert "C15" not in _fired(verdict)
    assert verdict.outcome is Outcome.COULDNT_CONFIRM


def test_gift_card_and_crypto_payments_fire():
    """Gift cards, game credits and crypto recur across ScamShield's pages as
    what scammers ask for, because the transfers cannot be reversed."""
    for action in (RequestedAction.BUY_GIFTCARD, RequestedAction.TRANSFER_CRYPTO):
        verdict = decide(Signals(requestedActions=(action,)))
        assert "C16" in _fired(verdict), action


def test_singpass_request_counts_as_a_credential_request():
    """ScamShield: "SPF officers will NEVER request your banking, SingPass
    and/or CPF related information"."""
    verdict = decide(Signals(requestedActions=(RequestedAction.SHARE_SINGPASS,)))
    assert "C4" in _fired(verdict)


def test_the_new_checks_stay_quiet_on_an_empty_conversation():
    """Five new checks, none of which should fire on nothing.

    Every check so far has been tested against scams. The failure that matters
    for a scam detector nobody uninstalls is the opposite one.
    """
    verdict = decide(Signals())
    assert not ({"C12", "C13", "C14", "C15", "C16"} & _fired(verdict))
    assert verdict.outcome is Outcome.COULDNT_CONFIRM


def test_channels_cover_what_real_advisories_name():
    """Campaigns are written from police advisories, and a campaign whose
    channel cannot be expressed matches nobody.

    These three came from advisories that named them: phishing "via iMessage"
    (Sept 2026), phishing emails impersonating DBS (Mar 2026), and government
    impersonation, which typically starts with a call.
    """
    values = {c.value for c in Channel}
    assert {"imessage", "email", "phone_call"} <= values
