"""Tests for the ScamShield guidance lookup.

The point of this data is that advice stops being whatever the model recalled.
These assert the lookup covers what the taxonomy can label and that the entries
carry the things advice has to get right - the helpline, and a source.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from knowledge import covered_lures, guidance_for  # noqa: E402
from pattern.taxonomy import LureType  # noqa: E402


def test_every_lure_the_model_can_label_has_guidance():
    """A category with no entry means advice falls back to saying less. That is
    the right failure, but it should be a decision rather than an oversight."""
    missing = {
        lure.value
        for lure in LureType
        if lure is not LureType.NONE and lure.value not in covered_lures()
    }
    assert not missing, f"no guidance for: {sorted(missing)}"


def test_no_guidance_for_an_unlabelled_conversation():
    assert guidance_for(LureType.NONE) is None


@pytest.mark.parametrize(
    "lure", [l for l in LureType if l is not LureType.NONE]
)
def test_every_entry_names_the_helpline(lure):
    """Advice previously cited a different source each run. 1799 is the number
    the workflow doc and ScamShield both give."""
    guidance = guidance_for(lure)
    assert "1799" in " ".join(guidance.whatToDo)


@pytest.mark.parametrize(
    "lure", [l for l in LureType if l is not LureType.NONE]
)
def test_every_entry_is_traceable(lure):
    """A claim like "banks never send links by SMS" is only as good as who said
    it and when."""
    guidance = guidance_for(lure)
    assert guidance.source.startswith("https://")
    assert guidance.retrieved
    assert guidance.keyTakeaway


def test_prompt_context_carries_the_rules_and_the_advice():
    guidance = guidance_for(LureType.LOAN)
    context = guidance.as_prompt_context()
    assert "Any unsolicited loan offer is a scam" in context
    assert "Registry of Moneylenders" in context
    assert "1799" in context


def test_checks_that_cite_a_rule_can_still_find_it():
    """C13 and C14 rest on lines in this file. If an edit removes one, the check
    it justifies has quietly lost its provenance."""
    assert any(
        "unsolicited loan offer is a scam" in rule
        for rule in guidance_for(LureType.LOAN).neverHappens
    )
    assert any(
        "helpline number in a pop-up" in rule
        for rule in guidance_for(LureType.TECH_SUPPORT).neverHappens
    )
