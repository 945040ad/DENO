"""Run the deterministic gates in order. L5 (the LLM judge) lives with the content graph and only runs
when these pass."""

from __future__ import annotations

from dataclasses import dataclass

from deno_gates.compliance import compliance
from deno_gates.gate import GateContext, GateResult
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


def run_gates(text: str, ctx: GateContext | None = None, *, profile: VoiceProfile | None = None) -> GateReport:
    ctx = ctx or GateContext()
    return GateReport(
        (
            scrub(text, ctx),
            patterns(text, ctx),
            density(text, ctx),
            structure(text, ctx),
            voice(text, ctx, profile=profile),
            compliance(text, ctx),
        )
    )
