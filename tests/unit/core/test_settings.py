import pytest

from deno_core.settings import Settings


def test_robots_opt_in_parses_comma_separated_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOURCES_ROBOTS_OPT_IN", " www.LinkedIn.com, cdn.syndication.twimg.com ,,")
    assert Settings(_env_file=None).sources_robots_opt_in == {"www.linkedin.com", "cdn.syndication.twimg.com"}  # type: ignore[call-arg]


def test_robots_opt_in_defaults_to_obeying_robots(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOURCES_ROBOTS_OPT_IN", raising=False)
    assert Settings(_env_file=None).sources_robots_opt_in == set()  # type: ignore[call-arg]
