"""The deterministic checks.

Checks C12 onward come from rules ScamShield publishes rather than from
judgement about what looks suspicious. Where their wording is categorical -
"banks will never send you any clickable links via SMS", "any unsolicited loan
offer is a scam" - the check is categorical too, and its docstring quotes the
line it rests on. That is a better provenance than weights fitted to whichever
screenshots happened to be at hand.

Source: scamshield.gov.sg, "Learn to recognise scams", retrieved 2026-09-06.

Each check is a pure function of labelled signals. No network, no model, no
clock, no randomness: the same conversation always produces the same result,
and the result can be explained to the person it is about.

Checks never read message text. They read labels produced upstream, which is
what stops a scam message from arguing with the check that catches it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .domains import impersonated_brand, is_allowlisted, near_miss_domain, registrable_domain
from .taxonomy import (
    Channel,
    ClaimedIdentity,
    LureType,
    ModelSuspicion,
    PressureTactic,
    RequestedAction,
    Signals,
)


@dataclass(frozen=True)
class CheckResult:
    id: str
    fired: bool
    detail: str = ""

    def __bool__(self) -> bool:
        return self.fired


def c1_unofficial_domain(signals: Signals) -> CheckResult:
    """A link whose owner we do not recognise.

    Weak on its own - most of the web is not on the allowlist - so this scores
    low and exists mainly to make the reasoning visible.
    """
    unknown = [u for u in signals.urls if not is_allowlisted(u)]
    if not unknown:
        return CheckResult("C1", False)
    owners = ", ".join(sorted({registrable_domain(u) or u for u in unknown}))
    return CheckResult("C1", True, f"Links to a domain we cannot verify: {owners}")


def c2_authority_claim_unofficial_link(signals: Signals) -> CheckResult:
    """Claims to be the police, a bank or the government, but links elsewhere.

    The strongest signal in the set. A real agency contacting you does not send
    you to a domain it does not own, so this is a hard trigger on its own.
    """
    if not signals.claims_authority():
        return CheckResult("C2", False)
    offending = [u for u in signals.urls if not is_allowlisted(u)]
    if not offending:
        return CheckResult("C2", False)
    owner = registrable_domain(offending[0]) or offending[0]
    return CheckResult(
        "C2",
        True,
        f"Claims to be {signals.claimedIdentity.value} but links to {owner}, "
        f"which is not an official domain",
    )


def c3_lookalike_domain(signals: Signals) -> CheckResult:
    """A link dressed up as an organisation that does not own it.

    Two ways to dress up: put the brand in a subdomain (mas-verify.sg-alert.test)
    or misspell the real domain (0cbc.com). Scores points rather than triggering
    outright, because brand-token matching can misfire and a false SCAM verdict
    teaches people to ignore real ones.
    """
    for url in signals.urls:
        brand = impersonated_brand(url)
        if brand:
            token, owner = brand
            return CheckResult(
                "C3", True,
                f'Uses the name "{token}" but the link is owned by {owner}',
            )
        near = near_miss_domain(url)
        if near:
            owner = registrable_domain(url) or url
            return CheckResult(
                "C3", True, f"{owner} is one or two characters away from {near}",
            )
    return CheckResult("C3", False)


def c4_credential_request(signals: Signals) -> CheckResult:
    """Asks for a password, banking login or one-time passcode.

    No legitimate organisation asks for these over chat, so the request itself
    is the signal regardless of who is asking.
    """
    asked = [
        a for a in signals.requestedActions
        if a in (
            RequestedAction.SHARE_CREDENTIALS,
            RequestedAction.SHARE_OTP,
            # "SPF officers will NEVER request your banking, SingPass and/or
            # CPF related information."
            RequestedAction.SHARE_SINGPASS,
        )
    ]
    if asked:
        wanted = " and ".join(a.value.replace("_", " ") for a in asked)
        return CheckResult(
            "C4", True,
            f"Asks the user to {wanted}, which no real bank or agency does",
        )
    return CheckResult("C4", False)


def c5_payment_under_authority(signals: Signals) -> CheckResult:
    """Asks for money while claiming to be an authority.

    The shape of nearly every impersonation scam that ends in a loss: the
    authority claim supplies the pressure, the transfer supplies the payday.
    """
    if signals.asks_for(RequestedAction.TRANSFER_MONEY) and signals.claims_authority():
        return CheckResult(
            "C5", True,
            f"Asks for a transfer while claiming to be {signals.claimedIdentity.value}",
        )
    return CheckResult("C5", False)


def c7_isolation(signals: Signals) -> CheckResult:
    """Tells the user to keep it quiet.

    Scams that survive contact with a third party are rare, so telling the
    victim not to tell anyone is load-bearing for the scammer and unusual for
    anyone else.
    """
    present = [
        t for t in signals.pressureTactics
        if t in (PressureTactic.SECRECY, PressureTactic.ISOLATION)
    ]
    if not present:
        return CheckResult("C7", False)
    return CheckResult(
        "C7", True,
        "Pressures the user to keep the conversation private "
        f"({', '.join(t.value for t in present)})",
    )


def c11_model_suspicion(signals: Signals) -> CheckResult:
    """The model's structural read, as a bounded contribution.

    Exists because the other checks are built around links, and whole scam
    families do not use one: an advance-fee approach with no URL fires nothing
    above and scores 15. This is the lever that lets the model raise a concern
    the structural checks cannot see.

    Scored, not decisive. It cannot reach the threshold alone, and nothing here
    can lower a verdict - a fired domain check stands regardless of what the
    model thinks.
    """
    if signals.modelSuspicion is ModelSuspicion.NONE:
        return CheckResult("C11", False)
    reason = signals.modelSuspicionReason.strip() or "no reason given"
    return CheckResult("C11", True, reason)


def c12_bank_link_over_sms(signals: Signals) -> CheckResult:
    """A link in an SMS that claims to come from a bank.

    ScamShield: "Banks will never send you any clickable links via SMS."

    Scored high rather than treated as decisive only because our channel
    detection is weak - it reports "unknown" more often than not - so this
    fires rarely and should not be the sole grounds for a verdict when it does.
    """
    if signals.claimedIdentity is not ClaimedIdentity.BANK:
        return CheckResult("C12", False)
    if signals.channel is not Channel.SMS or not signals.urls:
        return CheckResult("C12", False)
    return CheckResult(
        "C12", True,
        "Sends a link by SMS while claiming to be a bank. Banks never do this",
    )


def c13_unsolicited_loan_offer(signals: Signals) -> CheckResult:
    """A loan offered to someone who did not ask for one.

    ScamShield: "Any unsolicited loan offer is a scam." Licensed moneylenders
    are prohibited from advertising except in directories and on their own
    sites, so an approach offering a loan is either an unlicensed lender or a
    scammer, and neither is safe to deal with.

    Categorical in the source, so categorical here.
    """
    if signals.lureType is not LureType.LOAN or not signals.unsolicitedContact:
        return CheckResult("C13", False)
    return CheckResult(
        "C13", True,
        "Offers a loan you did not ask for. Licensed moneylenders are not "
        "allowed to advertise this way",
    )


def c14_remote_access_requested(signals: Signals) -> CheckResult:
    """Being talked into installing remote-access software.

    ScamShield: "Never download remote access applications at the request of an
    unsolicited caller, as this gives them full control of your device."

    The step that turns a tech-support scam into an emptied bank account: once
    the software is installed the scammer operates the victim's own banking
    session.
    """
    if not signals.asks_for(RequestedAction.INSTALL_REMOTE_ACCESS):
        return CheckResult("C14", False)
    if not signals.unsolicitedContact:
        return CheckResult("C14", False)
    return CheckResult(
        "C14", True,
        "Asks you to install software that hands over control of your device, "
        "after contacting you out of the blue",
    )


def c15_job_wants_money_first(signals: Signals) -> CheckResult:
    """A job that costs money to start.

    ScamShield lists as scam indicators that the job requires you to "pay
    upfront before starting" or "use your own money to complete tasks".

    Their wording is "likely a scam" rather than "never", so this scores instead
    of deciding: commission-based work exists, even if work that bills you does
    not.
    """
    if signals.lureType is not LureType.JOB:
        return CheckResult("C15", False)
    if not signals.asks_for(
        RequestedAction.PAY_UPFRONT_FEE,
        RequestedAction.TRANSFER_MONEY,
        RequestedAction.TRANSFER_CRYPTO,
    ):
        return CheckResult("C15", False)
    return CheckResult(
        "C15", True, "Offers work but asks you to pay or transfer money first",
    )


def c16_untraceable_payment(signals: Signals) -> CheckResult:
    """Payment demanded in a form that cannot be reversed.

    Gift cards, game credits and cryptocurrency appear across ScamShield's
    tech-support, romance and sexual-service pages as the payment methods
    scammers ask for. Their crypto page is explicit about why: "cryptocurrency
    transfers are non-reversible" and "difficult to trace".

    A legitimate seller has no reason to prefer a payment nobody can recover.
    """
    asked = [
        a for a in signals.requestedActions
        if a in (RequestedAction.BUY_GIFTCARD, RequestedAction.TRANSFER_CRYPTO)
    ]
    if not asked:
        return CheckResult("C16", False)
    how = " and ".join(a.value.replace("_", " ") for a in asked)
    return CheckResult(
        "C16", True,
        f"Wants payment by {how}, which cannot be reversed or traced",
    )


ALL_CHECKS = (
    c1_unofficial_domain,
    c2_authority_claim_unofficial_link,
    c3_lookalike_domain,
    c4_credential_request,
    c5_payment_under_authority,
    c7_isolation,
    c11_model_suspicion,
    c12_bank_link_over_sms,
    c13_unsolicited_loan_offer,
    c14_remote_access_requested,
    c15_job_wants_money_first,
    c16_untraceable_payment,
)


def run_checks(signals: Signals) -> tuple[CheckResult, ...]:
    """Every check, in order. Non-firing results are kept so the reasoning is
    inspectable rather than only its conclusions."""
    return tuple(check(signals) for check in ALL_CHECKS)
