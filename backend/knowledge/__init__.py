"""Official guidance, looked up by scam type.

The advice the app shows used to be whatever the model produced that run: one
run cited "the Singapore Police Force website", another said something else, and
neither was checked against what the authorities actually tell people. This
gives the model the published guidance for the scam type the pattern engine
already labelled, so advice becomes a rendering of official material rather
than a paraphrase from memory.

Selection is a dictionary lookup on that label. With twelve categories and a
known key there is nothing for a retrieval step to do.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from pattern.taxonomy import LureType

KNOWLEDGE_PATH = Path(__file__).parent / "scamshield.yaml"


@dataclass(frozen=True)
class ScamGuidance:
    """What ScamShield publishes about one kind of scam."""

    lure: str
    title: str
    source: str
    retrieved: str
    keyTakeaway: str
    neverHappens: tuple[str, ...] = ()
    redFlags: tuple[str, ...] = ()
    whatToDo: tuple[str, ...] = ()

    def as_prompt_context(self) -> str:
        """The entry as text for the advice prompt.

        Only one entry is ever included. Pasting the whole corpus would be
        ~15,000 tokens to answer a question that names its own category.
        """
        lines = [f"Official guidance for {self.title} (ScamShield, {self.retrieved}):"]
        if self.keyTakeaway:
            lines.append(f"Key point: {self.keyTakeaway.strip()}")
        if self.neverHappens:
            lines.append("Things that never happen legitimately:")
            lines += [f"- {item}" for item in self.neverHappens]
        if self.redFlags:
            lines.append("Recognised warning signs:")
            lines += [f"- {item}" for item in self.redFlags]
        if self.whatToDo:
            lines.append("Official advice for the user:")
            lines += [f"- {item}" for item in self.whatToDo]
        return "\n".join(lines)


@lru_cache(maxsize=1)
def _load() -> dict[str, ScamGuidance]:
    raw = yaml.safe_load(KNOWLEDGE_PATH.read_text(encoding="utf-8")) or {}
    return {
        lure: ScamGuidance(
            lure=lure,
            title=entry.get("title", lure),
            source=entry.get("source", ""),
            retrieved=str(entry.get("retrieved", "")),
            keyTakeaway=entry.get("keyTakeaway", ""),
            neverHappens=tuple(entry.get("neverHappens") or ()),
            redFlags=tuple(entry.get("redFlags") or ()),
            whatToDo=tuple(entry.get("whatToDo") or ()),
        )
        for lure, entry in raw.items()
    }


def guidance_for(lure: LureType) -> ScamGuidance | None:
    """Published guidance for a labelled scam type.

    Returns None for LureType.NONE, and for any category with no entry yet -
    the advice layer then falls back to saying less rather than inventing more.
    """
    if lure is LureType.NONE:
        return None
    return _load().get(lure.value)


def covered_lures() -> frozenset[str]:
    return frozenset(_load())
