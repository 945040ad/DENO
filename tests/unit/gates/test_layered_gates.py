import json
from pathlib import Path

from deno_gates import GateContext, autofix, build_profile, run_gates, scrub
from deno_gates.voice import voice

EVALS = Path(__file__).resolve().parents[3] / "evals" / "gates"


def _load(name: str) -> list[str]:
    return [json.loads(line)["text"] for line in (EVALS / name).read_text().splitlines() if line.strip()]


def _ai_fail(text: str, platform: str) -> bool:
    report = run_gates(text, GateContext(platform=platform))  # type: ignore[arg-type]
    return any(not r.passed for r in report.results if r.layer != "compliance")


def test_golden_corpus_thresholds() -> None:
    human = _load("human.jsonl")
    slop = _load("slop.jsonl")
    fpr = sum(_ai_fail(t, "reddit") for t in human) / len(human)
    catch = sum(_ai_fail(t, "linkedin") for t in slop) / len(slop)
    assert fpr <= 0.10, fpr
    assert catch >= 0.90, catch


def test_every_match_is_reported_with_position() -> None:
    text = "We delve into it. Then we delve again, a robust plan."
    findings = run_gates(text).results[1].findings
    assert [f.quote.lower() for f in findings] == ["delve", "delve", "robust"]
    assert text[findings[1].start : findings[1].end].lower() == "delve"


def test_unsourced_numbers_flagged_only_when_not_in_story_bank() -> None:
    ctx = GateContext(check_numbers=True, allowed_numbers=frozenset({"40"}))
    result = scrub("We grew 40% after cutting onboarding to 3 steps in 2024.", ctx)
    assert [f.quote for f in result.findings] == ["3"]


def test_autofix_is_mechanical() -> None:
    raw = "Sure! Here's a LinkedIn post about churn:\n\n**Churn** hurts — a lot.\n\nI hope this helps!"
    assert autofix(raw) == "Churn hurts, a lot."


def test_voice_delta_separates_authors() -> None:
    me = [
        "honestly i just ship stuff and see what sticks. last week i pushed three tiny fixes and one of them "
        "doubled signups which, lol, i did not expect at all. anyway back to it",
        "ok so the thing nobody tells you about cold email is that most of it is just follow up. i send like "
        "four follow ups and the third one gets the replies, every time, no idea why",
        "tried the fancy analytics tool for a month, went back to a spreadsheet. it's ugly but i actually look "
        "at it every morning with my coffee so it wins",
        "my cofounder and i argue about pricing basically every week. today he won. we're raising it again and "
        "i'm sure half the users will yell at us but whatever, we'll see",
    ]
    profile = build_profile(me)
    mine = (
        "so we raised prices again lol. two people yelled, nobody left. i keep thinking i should have done "
        "it months ago but whatever, it's done now and the spreadsheet looks way better. my cofounder says "
        "i told you so about every hour. honestly he was right, i just hate being the one who asks people for "
        "more money. anyway next up is the onboarding email, which is still bad"
    )
    formal = (
        "In today's competitive environment, organizations must carefully evaluate their pricing strategies. "
        "A structured approach enables leaders to align value with customer expectations and ensure growth. "
        "By leveraging data-driven insights, companies can identify opportunities to optimize revenue while "
        "maintaining customer satisfaction. Furthermore, transparent communication regarding changes is "
        "essential for preserving trust and long-term relationships with key stakeholders."
    )
    assert voice(mine, profile=profile).score < voice(formal, profile=profile).score  # type: ignore[operator]
    assert not profile.strong  # 4 short samples: advisory only
