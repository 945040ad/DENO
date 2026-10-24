"""Parsing the "Fix it for me" editor's answer, and the prompt it is given."""

from __future__ import annotations

import pytest

from deno_api.v1.content import parse_studio_edit
from deno_llm import get_prompt

POST = "Onboarding is about trust. We use a checklist so every new user gets a win on day one."


@pytest.mark.parametrize(
    "raw",
    [
        f"EDITED:\n{POST}\nWHAT CHANGED:\n- Cut the opener\n- utilize -> use\n",
        f"EDITED: {POST}\nWHAT CHANGED:\n- Cut the opener\n- utilize -> use",
        f"**EDITED:**\n{POST}\n\n**WHAT CHANGED:**\n* Cut the opener\n* utilize -> use",
        f"Edited:\n```\n{POST}\n```\nWhat changed:\n1. Cut the opener\n2) utilize -> use",
        f"EDITED:\r\n{POST}\r\nWHAT CHANGED:\r\n- Cut the opener\r\n- utilize -> use\r\n",
    ],
    ids=["canonical", "same-line", "markdown-bold", "fenced-numbered", "crlf"],
)
def test_reads_the_edit_however_the_model_dresses_it(raw: str) -> None:
    post, changes = parse_studio_edit(raw)
    assert post == POST
    assert changes == ["Cut the opener", "utilize -> use"]


def test_a_missing_change_list_still_returns_the_edit() -> None:
    assert parse_studio_edit(f"EDITED:\n{POST}") == (POST, [])


def test_change_lines_keep_their_own_numbers() -> None:
    _, changes = parse_studio_edit(f"EDITED:\n{POST}\nWHAT CHANGED:\n- 3 em dashes removed\n- 2 filler phrases cut")
    assert changes == ["3 em dashes removed", "2 filler phrases cut"]


def test_a_multi_paragraph_edit_survives_intact() -> None:
    post = "First paragraph stays.\n\nSecond paragraph too."
    assert parse_studio_edit(f"EDITED:\n{post}\nWHAT CHANGED:\n- nothing big")[0] == post


@pytest.mark.parametrize(
    "raw",
    [
        "Sure! Here is a better version of your post.",
        "I can't help with that.",
        "EDITED:\n\nWHAT CHANGED:\n- nothing",
        "EDITED:\n```\n```",
        "",
    ],
    ids=["chatty", "refusal", "empty-edit", "empty-fence", "nothing"],
)
def test_an_answer_without_a_real_edit_is_rejected(raw: str) -> None:
    """Never put a chat reply or a refusal in front of the founder as their post."""
    with pytest.raises(ValueError):
        parse_studio_edit(raw)


def test_the_change_list_is_capped() -> None:
    raw = f"EDITED:\n{POST}\nWHAT CHANGED:\n" + "\n".join(f"- change {i}" for i in range(50))
    assert len(parse_studio_edit(raw)[1]) == 20


def test_the_edit_prompt_renders_and_carries_the_rules_that_matter() -> None:
    prompt = get_prompt("studio.edit")
    rendered = "\n".join(
        str(m.content)
        for m in prompt.messages(platform="reddit", findings="- L2.vocab: robust", text="A {braced} post")
    )
    assert "A {braced} post" in rendered, "the founder's text is inserted verbatim, braces and all"
    assert "Respect the platform: reddit" in rendered
    for rule in ("Never add claims, examples, numbers", "minimum effective edit", "EDITED:", "WHAT CHANGED:"):
        assert rule in rendered


def test_judge_prompt_keeps_every_tell_and_the_fabrication_rule() -> None:
    """The content graph treats tell 21 as fabrication (always a fail) and 22 as "judge unavailable"."""
    system = get_prompt("content.judge").system
    for n in range(1, 22):
        assert f"{n} " in system, f"tell {n} missing"
    assert "21 FABRICATION" in system
