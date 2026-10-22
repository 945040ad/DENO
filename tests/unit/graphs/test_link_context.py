"""Reading the founder's link is optional context: no failure there may fail the run."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from deno_graphs.validation import nodes


class Ctx:
    def __init__(self) -> None:
        self.logs: list[str] = []

    async def emit(self, type_: str, **data: Any) -> None:
        self.logs.append(data.get("message", ""))


def deps() -> Any:
    return SimpleNamespace(ctx=Ctx(), settings=SimpleNamespace(github_token=SimpleNamespace(get_secret_value=str)))


async def test_a_bad_port_in_the_link_is_explained_not_raised() -> None:
    context, problem = await nodes._link_context(deps(), "My app lives at https://myapp.com:99999/ and it is great")
    assert context == ""
    assert problem == "that link has an invalid port number"


async def test_an_unexpected_error_reading_the_site_degrades_to_no_context(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(url: str) -> Any:
        raise RuntimeError("parser exploded")

    monkeypatch.setattr(nodes, "fetch_site", boom)
    context, problem = await nodes._link_context(deps(), "See tripnest.app for the product")
    assert context == ""
    assert problem == "tripnest.app couldn't be read"
