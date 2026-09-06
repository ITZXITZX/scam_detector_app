"""The vocabulary the whole system agrees on.

Three separate things depend on this list matching exactly: the prompt that asks
Claude to label a conversation, the checks that read those labels, and the
profile that counts them over time. Keeping it in one place means a typo is an
ImportError rather than a condition that silently never matches.

Every field is a closed enum. A value outside the enum is a bug, not a new
category: scoring is a lookup, and a lookup cannot handle a label it has never
seen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class LureType(str, Enum):
    """What the scam is pretending to be about.

    These are ScamShield's own categories, so a campaign described in the terms
    Singapore's anti-scam agencies use can be matched against a user profile
    without translation. Inventing our own would mean a "loan scam" advisory
    matching nobody.

    Two things deliberately absent. Cryptocurrency is not here: ScamShield's own
    page says crypto scams "fall into three main types - government officials
    impersonation, investment, job scams", so it is a payment rail rather than a
    lure, and listing it would split those three. Parcel is not here either; the
    phishing page treats parcel-delivery messages as a phishing variant.
    """

    AUTHORITY = "authority"          # government officials impersonation
    INVESTMENT = "investment"
    JOB = "job"
    ECOMMERCE = "ecommerce"
    PHISHING = "phishing"
    FAKE_FRIEND = "fake_friend"      # "I lost my phone, new number"
    LOAN = "loan"
    TECH_SUPPORT = "tech_support"
    INSURANCE = "insurance"
    ROMANCE = "romance"              # internet love
    SEXUAL_SERVICE = "sexual_service"
    # Anything outside ScamShield's list, including the advance-fee and
    # inheritance families their categories do not name.
    OTHER = "other"
    NONE = "none"


class PressureTactic(str, Enum):
    """How the other party is pushing the user toward acting."""

    URGENCY = "urgency"
    SECRECY = "secrecy"
    THREAT = "threat"
    ISOLATION = "isolation"  # "don't tell your family"
    FLATTERY = "flattery"
    RECIPROCITY = "reciprocity"
    AUTHORITY_CLAIM = "authority_claim"


class RequestedAction(str, Enum):
    """What the other party is asking the user to actually do.

    A conversation asks for several of these in sequence - click this, confirm
    your NRIC, then transfer - so Signals holds a list. Forcing a single "most
    consequential" action would hide the rest from every check that reads this
    field, and a check that cannot see its input fails silently.
    """

    TRANSFER_MONEY = "transfer_money"
    TRANSFER_CRYPTO = "transfer_crypto"
    SHARE_CREDENTIALS = "share_credentials"
    SHARE_OTP = "share_otp"
    SHARE_SINGPASS = "share_singpass"
    SHARE_ID_DOCUMENT = "share_id_document"
    INSTALL_APP = "install_app"
    INSTALL_REMOTE_ACCESS = "install_remote_access"
    CLICK_LINK = "click_link"
    BUY_GIFTCARD = "buy_giftcard"
    PAY_UPFRONT_FEE = "pay_upfront_fee"
    MEET_IN_PERSON = "meet_in_person"
    NONE = "none"


class ClaimedIdentity(str, Enum):
    """Who the other party says they are. Claimed, never verified."""

    POLICE = "police"
    BANK = "bank"
    GOVERNMENT = "government"
    COURIER = "courier"
    PLATFORM_SUPPORT = "platform_support"
    KNOWN_PERSON = "known_person"
    STRANGER = "stranger"
    NONE = "none"


class ModelSuspicion(str, Enum):
    """The model's structural read of the conversation.

    A label rather than a number, because a number the model chooses cannot be
    reproduced or explained - the reason this engine exists. Three options
    against a written rubric can at least be checked for stability: run the same
    conversation repeatedly and see whether the label moves.

    It feeds a scored check like any other signal, capped so it cannot decide a
    verdict alone, and it can only raise a verdict, never lower one.
    """

    NONE = "none"
    MODERATE = "moderate"
    STRONG = "strong"


class Channel(str, Enum):
    """Which app the conversation is happening in, read from the screenshot."""

    WHATSAPP = "whatsapp"
    TELEGRAM = "telegram"
    SMS = "sms"
    WECHAT = "wechat"
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    UNKNOWN = "unknown"


class EngagementDepth(str, Enum):
    """How far the user went before checking.

    Ordered least to most exposed. Workflow B weights recent encounters by this:
    someone who nearly transferred money counts for more than someone who
    checked before replying.
    """

    NO_REPLY = "no_reply"
    REPLIED = "replied"
    SHARED_PERSONAL_INFO = "shared_personal_info"
    SHARED_CREDENTIALS = "shared_credentials"
    INITIATED_PAYMENT = "initiated_payment"


# Identities whose real presence would always be on an official domain. Used by
# the check that catches "claims to be the police, links somewhere that isn't".
AUTHORITY_IDENTITIES = frozenset(
    {ClaimedIdentity.POLICE, ClaimedIdentity.BANK, ClaimedIdentity.GOVERNMENT}
)


@dataclass(frozen=True)
class Signals:
    """One conversation, labelled. The only input the deterministic checks get.

    Deliberately not the transcript: checks read structured labels so that the
    same conversation always produces the same verdict, and so a scam message
    cannot influence a check by what it says.
    """

    lureType: LureType = LureType.NONE
    pressureTactics: tuple[PressureTactic, ...] = ()
    requestedActions: tuple[RequestedAction, ...] = ()
    claimedIdentity: ClaimedIdentity = ClaimedIdentity.NONE
    channel: Channel = Channel.UNKNOWN
    engagementDepth: EngagementDepth = EngagementDepth.NO_REPLY
    urls: tuple[str, ...] = field(default_factory=tuple)
    # Whether the other party made contact out of the blue. Nearly every
    # ScamShield category begins with "unsolicited contact", and several of
    # their rules only hold for an approach the user did not initiate: a loan
    # advertisement is a scam when unsolicited and ordinary when answered.
    unsolicitedContact: bool = False
    # Whether the other party made contact out of the blue. Nearly every
    # ScamShield category begins with "unsolicited contact", and several of
    # their rules only hold for an approach the user did not initiate: a loan
    # advertisement is a scam when unsolicited and ordinary when answered.
    unsolicitedContact: bool = False
    # Whether the other party made contact out of the blue. Nearly every
    # ScamShield category begins with "unsolicited contact", and several of
    # their rules only hold for an approach the user did not initiate: a loan
    # advertisement is a scam when unsolicited and ordinary when answered.
    unsolicitedContact: bool = False
    modelSuspicion: ModelSuspicion = ModelSuspicion.NONE
    modelSuspicionReason: str = ""

    def claims_authority(self) -> bool:
        return self.claimedIdentity in AUTHORITY_IDENTITIES

    def asks_for(self, *actions: RequestedAction) -> bool:
        return any(a in self.requestedActions for a in actions)
