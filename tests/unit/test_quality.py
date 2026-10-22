"""Tests for the post-generation quality verification safeguard."""

from __future__ import annotations

import math

import pytest

from deno_gates.gate import CommunityRules, GateContext, GateResult
from deno_gates.pipeline import GateReport
from deno_gates.quality import (
    DEFAULT_THRESHOLD,
    DIMENSION_WEIGHTS,
    MAX_REGEN_ATTEMPTS,
    score_quality,
)
from deno_gates.voice import VoiceProfile, build_profile

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

GOOD_POST = (
    "Last month we hit $14,280 MRR after 42 cold emails to DevOps leads at Series-A startups. "
    "The trick was dead simple: I stopped pitching features and started asking what broke their "
    "last deploy. Three of them told me the same thing, their rollback took 90 minutes because "
    "nobody owned the runbook. We built the fix in a weekend. One customer, Acme Corp, cut their "
    "rollback time from 90 minutes to 8. That's the whole story. If you're in platform engineering, "
    "what does your rollback process look like?"
)

MEDIOCRE_POST = (
    "In today's fast-paced world, innovation is key to success. Our groundbreaking platform "
    "leverages cutting-edge technology to deliver robust solutions that drive transformative results. "
    "We are delighted to announce that our journey has led to significant growth. The landscape of "
    "technology is evolving, and we are at the forefront of this paradigm shift. Let's dive in!"
)

CLEAN_GATE_RESULT = GateResult("L1_scrub", True, ())
CLEAN_REPORT = GateReport(
    results=(
        GateResult("L1_scrub", True, ()),
        GateResult("L2_patterns", True, ()),
        GateResult("L3_density", True, (), score=0.0),
        GateResult("L4_structure", True, ()),
        GateResult("voice", True, (), score=None),
        GateResult("compliance", True, ()),
    )
)

DIRTY_REPORT = GateReport(
    results=(
        GateResult("L1_scrub", True, ()),
        GateResult(
            "L2_patterns",
            False,
            (
                GateResult.__class__,  # placeholder; use a real Finding below
            ),
        ),
        GateResult("L3_density", True, (), score=2.0),
        GateResult("L4_structure", True, ()),
        GateResult("voice", True, (), score=None),
        GateResult("compliance", True, ()),
    )
)


@pytest.fixture
def linkedin_ctx() -> GateContext:
    return GateContext(
        platform="linkedin",
        community=CommunityRules(name="startups", platform="linkedin"),
        is_promotional=False,
        allowed_numbers=frozenset({"14280", "42", "90", "8"}),
        allowed_number_words=frozenset({"three"}),
        check_numbers=True,
        story_attached=True,
    )


@pytest.fixture
def no_story_ctx() -> GateContext:
    return GateContext(
        platform="linkedin",
        community=CommunityRules(name="startups", platform="linkedin"),
        is_promotional=False,
        check_numbers=False,
        story_attached=False,
    )


@pytest.fixture
def voice_profile() -> VoiceProfile:
    samples = [
        "We spent six months building a feature nobody used. The usage dashboard showed three clicks a week, "
        "all from us. We killed it and our retention went up because we stopped confusing people.",
        "My advice for first-time founders: sell the thing before you build it. I wasted four months coding "
        "a billing module that two customers asked for. When I showed it to them, they said no thanks, "
        "they had already switched to Stripe.",
        "After three weeks of cold outreach I had twelve calls booked. Nine of them no-showed. The three "
        "that did show up all said the same thing: your landing page looks like every other dev tool.",
    ]
    return build_profile(samples)


# ---------------------------------------------------------------------------
# Quality scoring tests
# ---------------------------------------------------------------------------


class TestScoreQuality:
    def test_good_post_scores_above_threshold(self, linkedin_ctx: GateContext) -> None:
        verdict = score_quality(GOOD_POST, CLEAN_REPORT, linkedin_ctx, threshold=DEFAULT_THRESHOLD)
        assert verdict.overall_score >= 6.0, f"Good post should score well, got {verdict.overall_score}"
        assert isinstance(verdict.dimensions, tuple)
        assert len(verdict.dimensions) == 10

    def test_mediocre_post_scores_lower(self, no_story_ctx: GateContext) -> None:
        verdict = score_quality(MEDIOCRE_POST, CLEAN_REPORT, no_story_ctx, threshold=DEFAULT_THRESHOLD)
        good_verdict = score_quality(GOOD_POST, CLEAN_REPORT, no_story_ctx, threshold=DEFAULT_THRESHOLD)
        assert verdict.overall_score < good_verdict.overall_score, (
            f"Mediocre post ({verdict.overall_score}) should score lower than good post ({good_verdict.overall_score})"
        )

    def test_threshold_determines_pass(self, linkedin_ctx: GateContext) -> None:
        low = score_quality(GOOD_POST, CLEAN_REPORT, linkedin_ctx, threshold=1)
        high = score_quality(GOOD_POST, CLEAN_REPORT, linkedin_ctx, threshold=10)
        assert low.passed is True
        assert high.passed is False

    def test_llm_scores_are_used(self, linkedin_ctx: GateContext) -> None:
        without_llm = score_quality(GOOD_POST, CLEAN_REPORT, linkedin_ctx)
        with_llm = score_quality(
            GOOD_POST,
            CLEAN_REPORT,
            linkedin_ctx,
            llm_scores={"hook_strength": 10.0, "engagement_potential": 10.0, "originality_llm": 10.0},
        )
        assert with_llm.overall_score >= without_llm.overall_score

    def test_flaw_summary_populated_for_low_score(self, no_story_ctx: GateContext) -> None:
        verdict = score_quality(MEDIOCRE_POST, CLEAN_REPORT, no_story_ctx, threshold=9)
        assert not verdict.passed
        assert len(verdict.flaw_summary) > 20, "Flaw summary should contain actionable fixes"

    def test_to_dict_structure(self, linkedin_ctx: GateContext) -> None:
        verdict = score_quality(GOOD_POST, CLEAN_REPORT, linkedin_ctx)
        d = verdict.to_dict()
        assert "overall_score" in d
        assert "passed" in d
        assert "threshold" in d
        assert "dimensions" in d
        assert "flaw_summary" in d
        assert len(d["dimensions"]) == 10
        for dim in d["dimensions"]:
            assert "name" in dim
            assert "score" in dim
            assert "weight" in dim
            assert "flaws" in dim


class TestDimensionScoring:
    def test_specificity_rewards_numbers(self, linkedin_ctx: GateContext) -> None:
        with_numbers = score_quality(GOOD_POST, CLEAN_REPORT, linkedin_ctx)
        without_numbers = score_quality(
            "We did some stuff and it worked out pretty well for our team overall.", CLEAN_REPORT, linkedin_ctx
        )
        specificity_good = next(d for d in with_numbers.dimensions if d.name == "specificity")
        specificity_bad = next(d for d in without_numbers.dimensions if d.name == "specificity")
        assert specificity_good.score > specificity_bad.score

    def test_platform_fit_linkedin_length(self) -> None:
        short = "Hi."
        ctx = GateContext(platform="linkedin")
        verdict = score_quality(short, CLEAN_REPORT, ctx)
        fit = next(d for d in verdict.dimensions if d.name == "platform_fit")
        assert fit.score < 8.0, "Very short LinkedIn post should score low on platform fit"

    def test_readability_rewards_variety(self) -> None:
        varied = (
            "We shipped it. The first week was rough, with three customers reporting a timeout on the "
            "export endpoint that only showed up under load. Our fix took two days and cut latency by 60%. "
            "Not perfect, but good enough to keep going."
        )
        monotone = (
            "Word word word word word. Word word word word word. Word word word word word. Word word word word word."
        )
        v_verdict = score_quality(varied, CLEAN_REPORT, None)
        m_verdict = score_quality(monotone, CLEAN_REPORT, None)
        v_read = next(d for d in v_verdict.dimensions if d.name == "readability")
        m_read = next(d for d in m_verdict.dimensions if d.name == "readability")
        assert v_read.score >= m_read.score

    def test_voice_uses_profile(self, voice_profile: VoiceProfile, linkedin_ctx: GateContext) -> None:
        verdict = score_quality(GOOD_POST, CLEAN_REPORT, linkedin_ctx, profile=voice_profile)
        voice_dim = next(d for d in verdict.dimensions if d.name == "voice_authenticity")
        assert voice_dim.score is not None
        assert 0 <= voice_dim.score <= 10

    def test_story_grounding_penalises_fabrication(self, no_story_ctx: GateContext) -> None:
        fabricated = (
            "Last month a client told me they had been struggling with this for years. "
            "I spent three weeks building the fix. We shipped it and the results were incredible."
        )
        verdict = score_quality(fabricated, CLEAN_REPORT, no_story_ctx)
        story_dim = next(d for d in verdict.dimensions if d.name == "story_grounding")
        assert story_dim.score < 8.0, "Fabricated story with no Story Bank should score low"

    def test_originality_penalises_generic(self) -> None:
        generic = (
            "Success comes from hard work and dedication. Innovation is the key to growth. "
            "We believe in creating value for our stakeholders through excellence and commitment."
        )
        verdict = score_quality(generic, CLEAN_REPORT, None)
        orig = next(d for d in verdict.dimensions if d.name == "originality")
        assert orig.score < 7.0, f"Generic text should score low on originality, got {orig.score}"


class TestCustomWeightsAndThreshold:
    def test_custom_weights_shift_overall_score(self, linkedin_ctx: GateContext) -> None:
        """A founder who zeroes out a weak dimension's weight should see the overall score move."""
        default = score_quality(GOOD_POST, CLEAN_REPORT, linkedin_ctx)
        weak_dim = min(default.dimensions, key=lambda d: d.score)
        boosted = score_quality(GOOD_POST, CLEAN_REPORT, linkedin_ctx, custom_weights={weak_dim.name: 0.0})
        assert boosted.overall_score > default.overall_score

    def test_unknown_or_out_of_range_weights_are_ignored(self, linkedin_ctx: GateContext) -> None:
        default = score_quality(GOOD_POST, CLEAN_REPORT, linkedin_ctx)
        same = score_quality(
            GOOD_POST,
            CLEAN_REPORT,
            linkedin_ctx,
            custom_weights={"not_a_real_dimension": 5.0, "specificity": 99.0},
        )
        assert same.overall_score == default.overall_score

    def test_all_zero_weights_fall_back_to_defaults(self, linkedin_ctx: GateContext) -> None:
        default = score_quality(GOOD_POST, CLEAN_REPORT, linkedin_ctx)
        zeroed = score_quality(
            GOOD_POST, CLEAN_REPORT, linkedin_ctx, custom_weights=dict.fromkeys(DIMENSION_WEIGHTS, 0.0)
        )
        assert zeroed.overall_score == default.overall_score

    def test_pass_is_decided_on_the_score_that_is_shown(self, linkedin_ctx: GateContext) -> None:
        """A draft shown as 7.0 must not fail a bar of 7 because the unrounded score was 6.96."""
        verdict = score_quality(GOOD_POST, CLEAN_REPORT, linkedin_ctx)
        at_bar = score_quality(GOOD_POST, CLEAN_REPORT, linkedin_ctx, threshold=math.ceil(verdict.overall_score))
        assert at_bar.passed == (at_bar.overall_score >= at_bar.threshold)

    def test_threshold_from_adaptive_history(self) -> None:
        from deno_gates.quality import compute_adaptive_threshold

        # Oldest→newest, consistently strong: the bar should rise above the default 7.
        assert compute_adaptive_threshold([9.0, 9.0, 8.5, 9.0, 8.5]) > DEFAULT_THRESHOLD
        # Explicit user threshold always wins, clamped to [5, 9].
        assert compute_adaptive_threshold([9.0, 9.0, 9.0], user_threshold=3) == 5
        assert compute_adaptive_threshold([], user_threshold=None) == DEFAULT_THRESHOLD


class TestToGateLayer:
    def test_shape_and_meta(self, linkedin_ctx: GateContext) -> None:
        verdict = score_quality(GOOD_POST, CLEAN_REPORT, linkedin_ctx)
        layer = verdict.to_gate_layer()
        assert layer["layer"] == "quality_verification"
        assert layer["passed"] == verdict.passed
        assert layer["score"] == verdict.overall_score
        findings = layer["findings"]
        assert isinstance(findings, list)
        assert len(findings) == len(verdict.dimensions)
        assert all(f["rule_id"].startswith("quality.") for f in findings)
        meta = layer["meta"]
        assert meta["threshold"] == verdict.threshold
        assert meta["explanation"] == verdict.explanation
        assert len(meta["dimensions"]) == len(verdict.dimensions)
        # The real weight travels through meta, not baked into the findings message.
        by_name = {d["name"]: d for d in meta["dimensions"]}
        for dim in verdict.dimensions:
            assert by_name[dim.name]["weight"] == dim.weight
            assert by_name[dim.name]["score"] == dim.score

    def test_quality_findings_never_block_or_warn(self, linkedin_ctx: GateContext) -> None:
        """Quality is advisory: it must not feed the blocking/warning lists or the 0–100 gate score.

        The web client derives both from ``severity`` ('block' costs 15 points, 'warn' 5), so a
        below-bar dimension marked 'block' would silently drop a draft's ban-risk score and show
        blocking issues on a draft that is still GATED and approvable.
        """
        verdict = score_quality(GOOD_POST, CLEAN_REPORT, linkedin_ctx, threshold=9)
        below_bar = [d for d in verdict.dimensions if d.score < 9]
        assert below_bar, "fixture should have at least one dimension under 9 to exercise this"
        findings = verdict.to_gate_layer()["findings"]
        assert all(f["severity"] == "info" for f in findings)

    def test_below_bar_dimensions_say_so_in_the_message(self, linkedin_ctx: GateContext) -> None:
        verdict = score_quality(GOOD_POST, CLEAN_REPORT, linkedin_ctx, threshold=9)
        by_rule = {f["rule_id"]: f for f in verdict.to_gate_layer()["findings"]}
        for dim in verdict.dimensions:
            msg = by_rule[f"quality.{dim.name}"]["message"]
            assert ("below the 9/10 bar" in msg) is (dim.score < 9)


class TestQualityConstants:
    def test_default_threshold(self) -> None:
        assert DEFAULT_THRESHOLD == 7

    def test_max_regen_attempts(self) -> None:
        assert MAX_REGEN_ATTEMPTS == 3

    def test_dimension_weights_cover_all(self) -> None:
        from deno_gates.quality import DIMENSION_WEIGHTS

        expected = {
            "hook_strength",
            "specificity",
            "voice_authenticity",
            "platform_fit",
            "engagement_potential",
            "story_grounding",
            "slop_cleanliness",
            "readability",
            "originality",
            "community_compliance",
        }
        assert set(DIMENSION_WEIGHTS.keys()) == expected
