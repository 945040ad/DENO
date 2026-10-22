"""Thin evidence: retry when the shortfall is ours, answer at once when the evidence isn't there.

A transient Arctic Shift outage used to end the run as `insufficient_evidence` - a verdict about the
founder's idea caused by our collector. 3 of 10 good ideas in the eval ended that way.
"""

from typing import Any

from langgraph.types import Send

from deno_graphs.validation.nodes import (
    MAX_RETRY_QUERIES,
    broader_queries,
    fan_out_retry,
    insufficient_reasons,
    latest_errors,
    route_after_coverage,
)
from deno_graphs.validation.verdict import MAX_COLLECT_ROUNDS, coverage, decide_coverage

PLANNED = ["reddit", "hn", "x", "producthunt"]


def decide(by_source: dict[str, int], errors: dict[str, str | None] | None = None, rounds: int = 1):  # type: ignore[no-untyped-def]
    return decide_coverage(coverage(by_source, 0), planned=PLANNED, errors=errors or {}, rounds=rounds)


# ---- the decision ---------------------------------------------------------------------


def test_enough_evidence_goes_straight_on() -> None:
    d = decide({"reddit": 10, "hn": 5})
    assert (d.action, d.cause) == ("ok", "ok")


def test_a_source_that_failed_is_retried_not_judged() -> None:
    """Reddit timing out says nothing about the idea, however little else came back."""
    d = decide({"hn": 2}, {"reddit": "timeout", "hn": None, "x": None})
    assert d.action == "retry"
    assert d.cause == "sources_failed"
    assert "reddit" in d.retry_sources


def test_blocked_search_engines_count_as_a_failure() -> None:
    d = decide({"reddit": 4}, {"x": "unavailable: search engines blocked: brave (too many requests)"})
    assert d.action == "retry"
    assert "x" in d.retry_sources


def test_a_near_miss_broadens_the_thin_sources() -> None:
    """Every source answered, evidence exists but is short of the bar: one wider pass is worth it."""
    d = decide({"reddit": 6, "hn": 1, "x": 0})
    assert (d.action, d.cause) == ("retry", "thin")
    assert set(d.retry_sources) == {"hn", "x", "producthunt"}  # reddit already has 3+


def test_clean_and_nearly_empty_is_a_fast_honest_answer() -> None:
    """Every source answered and almost nothing exists: that is a real signal, don't make them wait."""
    d = decide({"reddit": 1, "hn": 1}, {"reddit": None, "hn": None, "x": None})
    assert (d.action, d.cause) == ("insufficient", "no_evidence")
    assert d.retry_sources == ()


def test_a_policy_block_is_never_retried() -> None:
    """robots.txt will say the same thing on the second pass."""
    d = decide({"reddit": 6, "hn": 1}, {"linkedin_posts": "blocked_by_policy", "x": "blocked_by_policy"})
    assert "x" not in d.retry_sources
    assert d.cause == "thin"


def test_at_most_one_retry() -> None:
    d = decide({"hn": 2}, {"reddit": "timeout"}, rounds=MAX_COLLECT_ROUNDS)
    assert d.action == "insufficient"
    assert d.cause == "sources_failed", "the reason must survive so the message can say it was us"


def test_failures_and_thin_sources_are_both_retried_on_a_near_miss() -> None:
    d = decide({"reddit": 5, "hn": 1}, {"x": "slow source (some queries timed out)"})
    assert d.retry_sources[0] == "x", "failed sources first"
    assert "hn" in d.retry_sources


# ---- the state plumbing -----------------------------------------------------------------


def result(source: str, error: str | None, failed: list[str] | None = None) -> dict[str, Any]:
    return {
        "source": source,
        "queries": [],
        "posts": [],
        "error": error,
        "seconds": 0.0,
        "failed_queries": failed or [],
    }


def test_a_successful_retry_clears_the_first_failure() -> None:
    """`collected` is append-only across passes, so the latest pass per source has to win."""
    errors = latest_errors([result("reddit", "timeout"), result("hn", None), result("reddit", None)])  # type: ignore[list-item]
    assert errors == {"reddit": None, "hn": None}


def test_runs_checkpointed_before_the_retry_still_route() -> None:
    brief = {"problem": "p", "solution": "s", "audience": "a"}
    assert route_after_coverage({"coverage": {"ok": False}, "brief": brief}) == "insufficient"  # type: ignore[typeddict-item]
    sends = route_after_coverage({"coverage": {"ok": True}, "brief": brief})  # type: ignore[typeddict-item]
    assert isinstance(sends, list) and all(isinstance(s, Send) for s in sends)


def test_retry_routes_to_broaden() -> None:
    assert route_after_coverage({"coverage": {"ok": False, "action": "retry"}}) == "broaden"  # type: ignore[typeddict-item]


def test_retry_fans_out_only_to_the_chosen_sources() -> None:
    sends = fan_out_retry(
        {"retry": {"x": {"queries": ["churn"], "subreddits": []}, "hn": {"queries": [], "subreddits": []}}}  # type: ignore[typeddict-item]
    )
    assert isinstance(sends, list)
    assert [s.arg["source"] for s in sends] == ["x"], "a source with nothing new to ask is skipped"


def test_nothing_left_to_try_ends_honestly() -> None:
    assert fan_out_retry({"retry": {}}) == "insufficient"  # type: ignore[typeddict-item]


# ---- broader queries ----------------------------------------------------------------------


def test_queries_that_never_answered_go_first() -> None:
    qs = broader_queries(["invoice reminders freelancers"], ["invoice reminders freelancers"], [])
    assert qs[0] == "invoice reminders freelancers"


def test_wider_variants_drop_words() -> None:
    """Full-text backends match every word: fewer words, more recall."""
    qs = broader_queries(["late invoice payment reminders"], [], [])
    assert qs and all(len(q.split()) <= 2 for q in qs)
    assert "late invoice payment reminders" not in qs, "a query that already answered is not re-asked"


def test_keywords_widen_too_and_the_list_is_capped() -> None:
    qs = broader_queries(["a b c"], [], ["accounts receivable", "dunning", "cash flow", "net 30", "collections"])
    assert "dunning" in qs
    assert len(qs) <= MAX_RETRY_QUERIES


# ---- the message ---------------------------------------------------------------------------


def test_failures_lead_the_reasons_and_policy_blocks_are_not_news() -> None:
    reasons = insufficient_reasons(
        {
            "source_errors": {"reddit": "timeout", "linkedin_posts": "blocked_by_policy"},
            "gaps": ["only 3 relevant public posts found (need at least 12)"],
        }
    )
    assert reasons[0] == "reddit failed (timeout)"
    assert not any("linkedin" in r for r in reasons)
    assert reasons[-1].startswith("only 3")
