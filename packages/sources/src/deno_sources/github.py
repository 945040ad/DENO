"""Read a public GitHub repository so an idea can be validated from its repo link.

Only api.github.com is called (a fixed host), never the URL the user typed, so a link can't point the
fetch at internal addresses. Everything returned is third-party text: callers must wrap it as untrusted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import httpx

API = "https://api.github.com"
README_LIMIT = 6000
_REPO = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9._-]{1,100})",
    re.IGNORECASE,
)
_RESERVED_OWNERS = {"orgs", "settings", "marketplace", "topics", "features", "about", "login", "sponsors"}
_BADGE = re.compile(r"\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)|!\[[^\]]*\]\([^)]*\)|<img[^>]*>", re.IGNORECASE)
_HTML_TAG = re.compile(r"</?[a-z][^>]*>", re.IGNORECASE)
_BLANKS = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class RepoFacts:
    owner: str
    name: str
    url: str
    description: str = ""
    homepage: str = ""
    language: str = ""
    topics: list[str] = field(default_factory=list)
    stars: int = 0
    readme: str = ""

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.name}"

    def as_text(self) -> str:
        lines = [f"Repository: {self.slug} ({self.url})"]
        if self.description:
            lines.append(f"Description: {self.description}")
        if self.homepage:
            lines.append(f"Website: {self.homepage}")
        if self.language:
            lines.append(f"Main language: {self.language}")
        if self.topics:
            lines.append(f"Topics: {', '.join(self.topics)}")
        lines.append(f"Stars: {self.stars}")
        if self.readme:
            lines.append(f"README:\n{self.readme}")
        return "\n".join(lines)


class RepoUnavailable(Exception):
    """The repo couldn't be read; ``reason`` is safe to show the founder."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def find_repo(text: str) -> tuple[str, str] | None:
    """First ``github.com/<owner>/<repo>`` link in the text, or None."""
    for m in _REPO.finditer(text):
        owner, name = m.group(1), m.group(2).removesuffix(".git").rstrip(".")
        if owner.lower() not in _RESERVED_OWNERS and name:
            return owner, name
    return None


def clean_readme(text: str, limit: int = README_LIMIT) -> str:
    text = _BADGE.sub("", text)
    text = _HTML_TAG.sub("", text)
    text = _BLANKS.sub("\n\n", text).strip()
    return text if len(text) <= limit else text[:limit].rsplit("\n", 1)[0] + "\n…(README truncated)"


async def fetch_repo(
    owner: str, name: str, *, token: str = "", client: httpx.AsyncClient | None = None, request_timeout_s: float = 10.0
) -> RepoFacts:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "deno-gtm"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    own = client is None
    http = client or httpx.AsyncClient(timeout=request_timeout_s, follow_redirects=False)
    try:
        try:
            meta = await http.get(f"{API}/repos/{owner}/{name}", headers=headers)
        except httpx.HTTPError as exc:
            raise RepoUnavailable("GitHub didn't respond, so the repo couldn't be read") from exc
        if meta.status_code == 404:
            raise RepoUnavailable(f"github.com/{owner}/{name} is private or doesn't exist")
        if meta.status_code in (403, 429):
            raise RepoUnavailable("GitHub's rate limit was reached, so the repo couldn't be read")
        if meta.status_code != 200:
            raise RepoUnavailable(f"GitHub answered {meta.status_code} for github.com/{owner}/{name}")
        data = meta.json()
        readme = ""
        try:
            r = await http.get(
                f"{API}/repos/{owner}/{name}/readme", headers={**headers, "Accept": "application/vnd.github.raw"}
            )
            if r.status_code == 200:
                readme = clean_readme(r.text)
        except httpx.HTTPError:
            readme = ""
        return RepoFacts(
            owner=str(data.get("owner", {}).get("login") or owner),
            name=str(data.get("name") or name),
            url=str(data.get("html_url") or f"https://github.com/{owner}/{name}"),
            description=str(data.get("description") or "").strip(),
            homepage=str(data.get("homepage") or "").strip(),
            language=str(data.get("language") or ""),
            topics=[str(t) for t in (data.get("topics") or [])][:12],
            stars=int(data.get("stargazers_count") or 0),
            readme=readme,
        )
    finally:
        if own:
            await http.aclose()
