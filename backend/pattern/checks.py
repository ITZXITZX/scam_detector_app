"""The deterministic checks.

Each check is a pure function of labelled signals. No network, no model, no
clock, no randomness: the same conversation always produces the same result,
and the result can be explained to the person it is about.

Checks never read message text. They read labels produced upstream, which is
what stops a scam message from arguing with the check that catches it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .domains import impersonated_brand, is_allowlisted, near_miss_domain, registrable_domain
from .taxonomy import PressureTactic, RequestedAction, Signals


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
    if signals.requestedAction in (RequestedAction.SHARE_CREDENTIALS, RequestedAction.SHARE_OTP):
        return CheckResult(
            "C4", True,
            f"Asks the user to {signals.requestedAction.value.replace('_', ' ')}, "
            f"which no real bank or agency does",
        )
    return CheckResult("C4", False)


def c5_payment_under_authority(signals: Signals) -> CheckResult:
    """Asks for money while claiming to be an authority.

    The shape of nearly every impersonation scam that ends in a loss: the
    authority claim supplies the pressure, the transfer supplies the payday.
    """
    if signals.requestedAction is RequestedAction.TRANSFER_MONEY and signals.claims_authority():
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


ALL_CHECKS = (
    c1_unofficial_domain,
    c2_authority_claim_unofficial_link,
    c3_lookalike_domain,
    c4_credential_request,
    c5_payment_under_authority,
    c7_isolation,
)


def run_checks(signals: Signals) -> tuple[CheckResult, ...]:
    """Every check, in order. Non-firing results are kept so the reasoning is
    inspectable rather than only its conclusions."""
    return tuple(check(signals) for check in ALL_CHECKS)
