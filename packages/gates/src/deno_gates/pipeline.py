"""Run the deterministic gates in order. L5 (the LLM judge) lives with the content graph and only runs
when these pass."""

from __future__ import annotations

from dataclasses import dataclass, replace

from deno_gates.compliance import compliance
from deno_gates.gate import Finding, GateContext, GateResult
from deno_gates.layers import density, patterns, scrub, structure
from deno_gates.voice import VoiceProfile, voice


@dataclass(frozen=True)
class GateReport:
    results: tuple[GateResult, ...]

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def failing(self) -> tuple[GateResult, ...]:
        return tuple(r for r in self.results if not r.passed)

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "layers": [
                {
                    "layer": r.layer,
                    "passed": r.passed,
                    "score": r.score,
                    "findings": [vars(f) for f in r.findings],
                }
                for r in self.results
            ],
        }


# Typographic apostrophes (phone keyboards, LLM output) -> ASCII, one character for one, so every match
# position still points into the original text. The rules spell apostrophes as "'", and without this
# "It’s not X. It’s Y." or "I’ve talked to…" (the invented-anecdote check) passed every gate.
_APOSTROPHES = str.maketrans({"\u2019": "'", "\u2018": "'", "\u02bc": "'", "\uff07": "'"})


def normalise(text: str) -> str:
    """The text the rules match against; same length as ``text``."""
    return text.translate(_APOSTROPHES)


def run_gates(text: str, ctx: GateContext | None = None, *, profile: VoiceProfile | None = None) -> GateReport:
    ctx = ctx or GateContext()
    matched = normalise(text)
    results = (
        scrub(matched, ctx),
        patterns(matched, ctx),
        density(matched, ctx),
        structure(matched, ctx),
        voice(matched, ctx, profile=profile),
        compliance(matched, ctx),
    )
    if matched == text:
        return GateReport(results)
    return GateReport(tuple(replace(r, findings=tuple(_quote_original(f, text) for f in r.findings)) for r in results))


def _quote_original(finding: Finding, text: str) -> Finding:
    """Quote the founder's own characters back, not the normalised ones."""
    if finding.end <= finding.start:
        return finding
    return replace(finding, quote=text[finding.start : finding.end].strip()[:160])
