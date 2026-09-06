"""URL parsing and lookalike detection.

The job here is to answer one question honestly: who actually owns this link?

Everything to the left of the registrable domain is chosen by whoever controls
the domain, so "dbs.com.sg.secure-login.co" belongs to secure-login.co and
"mas-verify.sg-alert.test" belongs to sg-alert.test. A person skims the start of
a URL and reads the brand; this module reads the end.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

ALLOWLIST_PATH = Path(__file__).parent / "allowlist.txt"

# Multi-label public suffixes we care about. This is a deliberate subset of the
# Public Suffix List: pulling the real PSL means either a network fetch (which
# would make verdicts depend on the network) or a large vendored file that goes
# stale. Anything not listed here falls back to "last label is the suffix",
# which is correct for .com, .test, .co and most gTLDs.
#
# Consequence worth knowing: a lookalike registered under an exotic multi-label
# suffix we have not listed would have its owner computed one label too short.
# That makes the check more suspicious, not less, so it fails safe.
_MULTI_LABEL_SUFFIXES = frozenset(
    {
        "com.sg", "gov.sg", "edu.sg", "net.sg", "org.sg", "per.sg",
        "com.my", "gov.my", "com.au", "gov.au", "co.uk", "gov.uk",
        "com.hk", "com.cn", "co.id", "co.th", "com.ph", "co.nz",
    }
)

# Hosts split into tokens on anything that is not a letter or digit, so
# "mas-verify.sg_alert" becomes [mas, verify, sg, alert].
_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class AllowlistEntry:
    domain: str          # "dbs.com.sg", or "gov.sg" for a "*." wildcard line
    wildcard: bool       # True when subdomains are covered too
    brands: tuple[str, ...]


@lru_cache(maxsize=1)
def load_allowlist(path: Path | None = None) -> tuple[AllowlistEntry, ...]:
    """Parse allowlist.txt. Cached: it is a checked-in file, not live data."""
    entries: list[AllowlistEntry] = []
    for raw in (path or ALLOWLIST_PATH).read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        domain, brands = parts[0].lower(), tuple(p.lower() for p in parts[1:])
        wildcard = domain.startswith("*.")
        entries.append(
            AllowlistEntry(domain=domain[2:] if wildcard else domain,
                           wildcard=wildcard, brands=brands)
        )
    return tuple(entries)


def registrable_domain(url_or_host: str) -> str | None:
    """The part of a URL that identifies its owner, or None if unparseable.

    >>> registrable_domain("https://mas-verify.sg-alert.test/case/114872")
    'sg-alert.test'
    >>> registrable_domain("https://dbs.com.sg.secure-login.co/login")
    'secure-login.co'
    >>> registrable_domain("https://www.police.gov.sg/advisories")
    'police.gov.sg'
    """
    candidate = url_or_host.strip()
    if not candidate:
        return None
    if "//" not in candidate:
        candidate = "//" + candidate  # urlsplit needs a scheme or leading //

    host = urlsplit(candidate).hostname
    if not host:
        return None
    host = host.strip(".").lower()
    if not host or " " in host:
        return None

    labels = host.split(".")
    if len(labels) < 2:
        return None  # bare hostname or an IP-ish single label

    if ".".join(labels[-2:]) in _MULTI_LABEL_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def is_allowlisted(url_or_host: str) -> bool:
    """True when the link's owner is an organisation we recognise."""
    domain = registrable_domain(url_or_host)
    if domain is None:
        return False
    for entry in load_allowlist():
        if domain == entry.domain:
            return True
        if entry.wildcard and domain.endswith("." + entry.domain):
            return True
    return False


def host_tokens(url_or_host: str) -> tuple[str, ...]:
    """Every whole-word component of the host.

    Token matching rather than substring matching is what stops "christmas"
    from looking like the Monetary Authority of Singapore.
    """
    candidate = url_or_host if "//" in url_or_host else "//" + url_or_host
    host = (urlsplit(candidate).hostname or "").lower()
    return tuple(t for t in _TOKEN_SPLIT.split(host) if t)


def impersonated_brand(url_or_host: str) -> tuple[str, str] | None:
    """Detect a brand token used by a host that does not belong to that brand.

    Returns (brand, owning_domain) or None. Only fires when the link is NOT
    allowlisted, so a real bank URL containing its own brand is never flagged.

    >>> impersonated_brand("https://mas-verify.sg-alert.test/case/114872")
    ('mas', 'sg-alert.test')
    >>> impersonated_brand("https://www.mas.gov.sg/news")   # genuine
    >>> impersonated_brand("https://christmas-deals.com")   # not a brand token
    """
    if is_allowlisted(url_or_host):
        return None
    owner = registrable_domain(url_or_host)
    if owner is None:
        return None

    # Tokens belonging to the owner itself are not impersonation: a site really
    # called "trust.sg" should not be flagged for containing "trust".
    owner_tokens = set(_TOKEN_SPLIT.split(owner))
    tokens = set(host_tokens(url_or_host)) - owner_tokens

    for entry in load_allowlist():
        for brand in entry.brands:
            if brand in tokens:
                return brand, owner
    return None


def _edit_distance(a: str, b: str, limit: int) -> int:
    """Levenshtein distance, giving up once it is certain to exceed `limit`."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb))
            )
        if min(current) > limit:
            return limit + 1
        previous = current
    return previous[-1]


def near_miss_domain(url_or_host: str, max_distance: int = 2) -> str | None:
    """An allowlisted domain this link is suspiciously close to spelling.

    Catches typosquats ("dbs.com.sq") that token matching misses because the
    brand is never a clean token.

    >>> near_miss_domain("https://0cbc.com/login")
    'ocbc.com'
    """
    if is_allowlisted(url_or_host):
        return None
    domain = registrable_domain(url_or_host)
    if domain is None:
        return None

    best: tuple[int, str] | None = None
    for entry in load_allowlist():
        if entry.wildcard:
            continue  # "gov.sg" is short enough that near misses are noise
        distance = _edit_distance(domain, entry.domain, max_distance)
        if distance <= max_distance and (best is None or distance < best[0]):
            best = (distance, entry.domain)
    return best[1] if best else None
