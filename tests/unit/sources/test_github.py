import httpx
import pytest
import respx

from deno_sources.github import RepoUnavailable, clean_readme, fetch_repo, find_repo


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://github.com/eimun/TravelJournal this is my project", ("eimun", "TravelJournal")),
        ("see github.com/foo-bar/baz.js.git for the code", ("foo-bar", "baz.js")),
        ("https://www.github.com/a/b/tree/main/src", ("a", "b")),
        ("https://github.com/orgs/acme/projects", None),
        ("A tool that scores LinkedIn drafts", None),
        ("https://gitlab.com/a/b", None),
    ],
)
def test_find_repo(text: str, expected: tuple[str, str] | None) -> None:
    assert find_repo(text) == expected


def test_clean_readme_drops_badges_and_html_and_truncates() -> None:
    raw = "[![ci](https://x/badge.svg)](https://x)\n# Travel Journal\n<p align=center><img src=a.png></p>\n\n\n\nLog trips."
    assert clean_readme(raw) == "# Travel Journal\n\nLog trips."
    long = "\n".join(f"line {i}" for i in range(2000))
    out = clean_readme(long, limit=100)
    assert len(out) < 140 and out.endswith("…(README truncated)")


@respx.mock
async def test_fetch_repo_reads_metadata_and_readme() -> None:
    respx.get("https://api.github.com/repos/eimun/TravelJournal").respond(
        json={
            "name": "TravelJournal",
            "owner": {"login": "eimun"},
            "html_url": "https://github.com/eimun/TravelJournal",
            "description": "Journal your trips with photos and maps",
            "homepage": "",
            "language": "Kotlin",
            "topics": ["android", "travel"],
            "stargazers_count": 3,
        }
    )
    readme = respx.get("https://api.github.com/repos/eimun/TravelJournal/readme").respond(
        text="# TravelJournal\nOffline trip log."
    )
    repo = await fetch_repo("eimun", "TravelJournal", token="t0k")
    assert repo.description == "Journal your trips with photos and maps"
    assert repo.topics == ["android", "travel"] and repo.language == "Kotlin"
    assert repo.readme == "# TravelJournal\nOffline trip log."
    assert "Topics: android, travel" in repo.as_text()
    assert readme.calls.last.request.headers["Authorization"] == "Bearer t0k"


@respx.mock
@pytest.mark.parametrize(
    ("status", "phrase"), [(404, "private or doesn't exist"), (403, "rate limit"), (500, "answered 500")]
)
async def test_fetch_repo_explains_failures(status: int, phrase: str) -> None:
    respx.get("https://api.github.com/repos/a/b").respond(status_code=status)
    with pytest.raises(RepoUnavailable, match=phrase):
        await fetch_repo("a", "b")


@respx.mock
async def test_missing_readme_is_not_fatal() -> None:
    respx.get("https://api.github.com/repos/a/b").respond(json={"name": "b", "description": "d"})
    respx.get("https://api.github.com/repos/a/b/readme").respond(status_code=404)
    repo = await fetch_repo("a", "b")
    assert repo.readme == "" and repo.description == "d"


@respx.mock
async def test_network_error_is_reported() -> None:
    respx.get("https://api.github.com/repos/a/b").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(RepoUnavailable, match="didn't respond"):
        await fetch_repo("a", "b")
