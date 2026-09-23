"""Gate contract: every layer is a pure function ``(text, ctx) -> GateResult``."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Severity = Literal["block", "warn"]


@dataclass(frozen=True)
class Finding:
    rule_id: str
    message: str
    quote: str
    start: int
    end: int
    fix: str
    severity: Severity = "block"


@dataclass(frozen=True)
class GateResult:
    layer: str
    passed: bool
    findings: tuple[Finding, ...] = ()
    score: float | None = None  # layer-specific (density per 100 words, delta, …); None when not scored

    @property
    def blocking(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity == "block")


@dataclass(frozen=True)
class CommunityRules:
    """What a community allows (from the ``community_rules`` table)."""

    name: str = ""
    platform: Literal["reddit", "linkedin", "x", "hn"] = "linkedin"
    promo_policy: str | None = None
    ai_policy: str | None = None
    links_allowed: bool = True
    value_to_promo_ratio: int | None = None


@dataclass(frozen=True)
class GateContext:
    platform: Literal["reddit", "linkedin", "x", "hn"] = "linkedin"
    community: CommunityRules | None = None
    is_promotional: bool = False
    # Facts the author actually has (Story Bank): any number in a draft must come from here.
    allowed_numbers: frozenset[str] = frozenset()
    allowed_number_words: frozenset[str] = frozenset()  # spelled-out counts ("three") found in the Story Bank
    check_numbers: bool = False
    # False = no Story Bank entry backs this post, so it may not narrate first-person experiences.
    # None = don't check (audit playground, human-written text).
    story_attached: bool | None = None
    voice_samples: tuple[str, ...] = ()
    extra: dict[str, str] = field(default_factory=dict)
