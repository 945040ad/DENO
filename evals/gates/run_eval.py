"""Gates eval: false-positive rate on real human posts (target ≤10%) and catch rate on default AI posts.

uv run python evals/gates/run_eval.py [-v]
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from deno_gates import GateContext, run_gates

HERE = Path(__file__).parent


def load(name: str) -> list[dict[str, str]]:
    return [json.loads(line) for line in (HERE / name).read_text().splitlines() if line.strip()]


def main() -> int:
    verbose = "-v" in sys.argv
    human, slop = load("human.jsonl"), load("slop.jsonl")
    fp_rules: Counter[str] = Counter()
    fps = 0
    for item in human:
        platform = "reddit" if item["source"].startswith("r/") else "linkedin"
        report = run_gates(item["text"], GateContext(platform=platform, is_promotional=True))
        # Compliance (links, promo) is about community rules, not about sounding like AI.
        failing = [f for r in report.failing if r.layer != "compliance" for f in r.blocking]
        if failing:
            fps += 1
            fp_rules.update({f.rule_id for f in failing})
            if verbose:
                print("FP:", [(f.rule_id, f.quote[:50]) for f in failing][:4])
    caught = 0
    miss_examples = []
    for item in slop:
        platform = "reddit" if "Reddit" in item["source"] else "linkedin"
        report = run_gates(item["text"], GateContext(platform=platform, is_promotional=True))
        if any(not r.passed for r in report.results if r.layer != "compliance"):
            caught += 1
        else:
            miss_examples.append(item["text"][:200])
    result = {
        "false_positive_rate": round(fps / len(human), 3),
        "slop_catch_rate": round(caught / len(slop), 3),
        "fp_rules": dict(fp_rules.most_common(10)),
    }
    print(json.dumps(result, indent=2))
    if verbose:
        for m in miss_examples[:5]:
            print("MISS:", m.replace("\n", " "))
    return 0 if result["false_positive_rate"] <= 0.10 and result["slop_catch_rate"] >= 0.9 else 1


if __name__ == "__main__":
    sys.exit(main())
