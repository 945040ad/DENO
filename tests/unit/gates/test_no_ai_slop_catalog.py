"""Patterns synced from petergyang/no-ai-slop: each catches its slop example and spares a human near-miss.

The gates eval (evals/gates) measures the false-positive rate on real posts; these pin each rule's edges.
"""

from __future__ import annotations

import pytest

from deno_gates import GateContext, run_gates


def rule_hits(text: str) -> dict[str, str]:
    report = run_gates(text, GateContext(platform="linkedin"))
    return {f.rule_id: f.severity for r in report.results for f in r.findings}


@pytest.mark.parametrize(
    ("slop", "rule", "severity"),
    [
        ("We utilize a shared inbox so support can reply faster.", "L2.vocab", "block"),
        ("The new flow helps streamline onboarding for small teams.", "L2.vocab", "block"),
        ("Honestly this changes everything for how we ship.", "L2.vocab", "block"),
        ("When it comes to pricing, most founders guess.", "L2.filler_phrase", "warn"),
        ("Going forward, we will publish the changelog weekly.", "L2.filler_phrase", "warn"),
        ("The question isn't the model. It's the eval.", "L2.binary_contrast", "block"),
        ("The bottleneck was never the code, it was the review queue.", "L2.binary_contrast", "block"),
        ("I'll be honest, our first launch flopped.", "L2.opener.hook", "block"),
        ("The best part: it learns from every reply.", "L2.colon_reveal", "block"),
        ("The part nobody talks about: distribution.", "L2.colon_reveal", "block"),
        ("Here's why this matters for small shops.", "L2.metadiscourse", "block"),
        ("We cut the scope. And shipped. And nobody noticed.", "L2.dramatic_fragments", "block"),
        ("Think about it: every tab is a tax.", "L2.rhetorical_theatre", "block"),
        ("We doubled the price. The result? Fewer refunds.", "L2.self_answered", "block"),
        ("Why? Because the old plan had no annual option.", "L2.self_answered", "block"),
        (
            "We changed pricing twice this year.\n\nUltimately, pricing is a product decision.",
            "L2.recap_opener",
            "warn",
        ),
        ("Pricing pages are hard — we rewrote ours twice.", "L1.em_dash", "warn"),
    ],
)
def test_catches_the_skill_example(slop: str, rule: str, severity: str) -> None:
    hits = rule_hits(slop)
    assert hits.get(rule) == severity, hits


@pytest.mark.parametrize(
    "human",
    [
        "In order to file the return I needed last year's receipts.",  # "in order to" is ordinary English, not listed
        "The question isn't settled yet, so we're testing both prices.",  # no "it's Y" reveal
        "Honest feedback from three customers changed our roadmap.",
        "The result was fewer refunds after we doubled the price.",  # plain sentence, no Q/A theatre
        "We shipped it and then we fixed the bugs.",
        "Overall the quarter went fine, churn stayed flat.",  # recap opener only counts as a closing paragraph
        "Note: the beta closes Friday.",
    ],
)
def test_spares_human_near_misses(human: str) -> None:
    hits = rule_hits(human)
    new_rules = {
        "L2.filler_phrase",
        "L2.binary_contrast",
        "L2.opener.hook",
        "L2.colon_reveal",
        "L2.metadiscourse",
        "L2.dramatic_fragments",
        "L2.self_answered",
        "L2.recap_opener",
        "L2.vocab",
    }
    assert not new_rules & set(hits), hits


def test_a_long_post_may_keep_one_em_dash() -> None:
    long_post = ("We rewrote the pricing page after talking to customers about annual plans. " * 12) + (
        "The annual option, the one people kept asking for, is now the default — finally."
    )
    assert "L1.em_dash" not in rule_hits(long_post)
