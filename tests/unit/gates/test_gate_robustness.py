"""Gate behaviour that must hold for any text, plus the regressions found reviewing the no-ai-slop sync."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from deno_gates import GateContext, autofix, numbers_in, run_gates
from deno_gates.pipeline import normalise


def hits(text: str, platform: str = "linkedin", **ctx: object) -> dict[str, str]:
    report = run_gates(text, GateContext(platform=platform, **ctx))  # type: ignore[arg-type]
    return {f.rule_id: f.severity for r in report.results for f in r.findings}


# ---- typographic apostrophes ----------------------------------------------------------------

CURLY = "’"


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("It's not a tool. It's a teammate.", "L2.binary_contrast"),
        ("Onboarding isn't about features. It's about trust.", "L2.binary_contrast"),
        ("Here's the thing: we shipped.", "L2.opener.hook"),
        ("I'll be honest, the launch flopped.", "L2.opener.hook"),
        ("That's it. That's the whole thing.", "L2.staccato"),
        ("Here's why this matters for small shops.", "L2.metadiscourse"),
        ("It's worth noting that churn fell.", "L2.metadiscourse"),
        ("Let's dive in.", "L2.vocab"),
    ],
)
def test_typographic_apostrophes_are_caught_like_straight_ones(text: str, rule: str) -> None:
    """Phone keyboards and LLMs write ’; every rule spells it '. Before normalising, all of these passed."""
    assert rule in hits(text), "straight apostrophe"
    assert rule in hits(text.replace("'", CURLY)), "typographic apostrophe"


def test_an_invented_anecdote_with_a_typographic_apostrophe_is_still_blocked() -> None:
    text = f"I{CURLY}ve talked to dozens of founders and they all say the same thing."
    assert hits(text, story_attached=False).get("L1.unsourced_story") == "block"


def test_findings_quote_the_founders_own_characters_at_the_right_place() -> None:
    text = f"Honestly? It{CURLY}s not a tool. It{CURLY}s a teammate."
    report = run_gates(text, GateContext(platform="linkedin"))
    finding = next(f for r in report.results for f in r.findings if f.rule_id == "L2.binary_contrast")
    assert CURLY in finding.quote
    assert text[finding.start : finding.end].strip() == finding.quote


# ---- dashes and ranges ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text", ["Office hours are 9–5 on weekdays.", "We ran it from 2019–2021.", "Pages 10–12 cover pricing."]
)
def test_en_dash_ranges_are_not_dashes(text: str) -> None:
    assert "L1.em_dash" not in hits(text)
    assert autofix(text) == text, "a range keeps its meaning"


def test_real_dashes_are_still_fixed_next_to_a_range() -> None:
    assert autofix("Open 9–5 — weekdays only.") == "Open 9–5, weekdays only."


# ---- self-answered questions, fragments and recaps ------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Any idea why? It broke after the update yesterday.",
        "What was the result? Nobody on the team could say.",
        "Does anyone know how? The docs say nothing.",
    ],
)
def test_real_questions_are_not_self_answered_theatre(text: str) -> None:
    assert "L2.self_answered" not in hits(text, platform="reddit")


@pytest.mark.parametrize(
    "text",
    [
        "We doubled the price. The result? Fewer refunds.",
        "Why? Because the old plan had no annual option.",
        "We tested it for a month.\nThe answer? Nobody used it.",
    ],
)
def test_self_answered_questions_are_caught_as_their_own_sentence(text: str) -> None:
    assert hits(text).get("L2.self_answered") == "block"


def test_lowercase_and_is_not_dramatic_fragmentation() -> None:
    assert "L2.dramatic_fragments" not in hits("We tried ads. and then email. and then nothing worked.")


def test_recap_warning_is_for_the_closing_paragraph_only() -> None:
    middle = "Three things happened.\n\nOverall, churn fell after the change.\n\nThen we raised prices."
    story = "We almost quit twice.\n\nIn the end, we sold the company to a competitor."
    closing = "We changed pricing twice.\n\nOverall, pricing is a product decision."
    assert "L2.recap_opener" not in hits(middle)
    assert "L2.recap_opener" not in hits(story)
    assert hits(closing).get("L2.recap_opener") == "warn"


# ---- properties ------------------------------------------------------------------------------

SLOPPY_TEXT = st.text(
    alphabet=st.sampled_from(list("abcdefghijklmnopqrstuvwxyz ITHAW.,:;?!'’‘—–-\n0123456789%$")),
    max_size=400,
)


@settings(max_examples=300, deadline=None)
@given(SLOPPY_TEXT)
def test_normalising_never_moves_a_character(text: str) -> None:
    assert len(normalise(text)) == len(text)


@settings(max_examples=300, deadline=None)
@given(SLOPPY_TEXT)
def test_every_quote_is_the_founders_own_text_at_its_position(text: str) -> None:
    for result in run_gates(text, GateContext(platform="linkedin", check_numbers=True)).results:
        for f in result.findings:
            assert 0 <= f.start <= f.end <= len(text)
            if f.end > f.start:
                assert f.quote == text[f.start : f.end].strip()[:160]


@settings(max_examples=300, deadline=None)
@given(SLOPPY_TEXT)
def test_autofix_is_idempotent(text: str) -> None:
    once = autofix(text)
    assert autofix(once) == once


@settings(max_examples=300, deadline=None)
@given(st.text(alphabet=st.sampled_from(list("abc ,.—–-0123456789%")), max_size=200))
def test_autofix_never_changes_a_number(text: str) -> None:
    """Mechanical fixes may touch dashes and spacing, never the figures a founder wrote."""
    assert numbers_in(autofix(text)) == numbers_in(text)
