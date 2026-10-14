"""Read the founder's product website (one page) so an idea can be validated from its URL.

The URL comes from the user, so this is the SSRF-sensitive path. For every hop (the page, each
redirect, robots.txt):

- https only, default port only, no credentials in the URL;
- the host is resolved and *every* address must be public (no private, loopback, link-local such as
  the cloud metadata server, reserved, multicast or unspecified);
- the connection goes to the exact address that was checked (TLS still verifies the real hostname via
  SNI), so DNS can't be swapped between the check and the fetch;
- redirects are followed by hand (at most 3), each re-checked;
- robots.txt is honoured for our crawler token;
- HTML only, at most 1 MB read, 10 s per request.

Everything returned is third-party text: callers must wrap it as untrusted.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx
from selectolax.parser import HTMLParser

from deno_sources.net import DEFAULT_UA, ROBOTS_TOKEN, Resolver, _is_public, system_resolver

MAX_BYTES = 1_000_000
MAX_REDIRECTS = 3
TEXT_LIMIT = 6000
THIN_TEXT = 200

# Links with a scheme, or bare domains like "myapp.com/pricing". GitHub is handled by deno_sources.github.
_URL = re.compile(r"\bhttps?://[^\s<>\"'()\[\]]+", re.IGNORECASE)
_BARE = re.compile(
    r"(?<![@\w.-])((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24})(/[^\s<>\"'()\[\]]*)?(?![\w-])",
    re.IGNORECASE,
)
_SKIP_HOSTS = ("github.com", "www.github.com")
_NOT_TLDS = {"js", "ts", "py", "md", "json", "txt", "png", "jpg", "jpeg", "gif", "svg", "css", "html", "sh", "go", "rs"}
_DROP = "script, style, noscript, svg, template, iframe, nav, footer, form, [aria-hidden=true]"
_WS = re.compile(r"[ \t\r\f\v]+")
_LINES = re.compile(r"\n\s*\n+")


class SiteUnavailable(Exception):
    """The page couldn't be read; ``reason`` is safe to show the founder."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class SiteFacts:
    url: str
    title: str = ""
    description: str = ""
    headings: list[str] = field(default_factory=list)
    pricing: str = ""
    text: str = ""

    @property
    def host(self) -> str:
        return urlsplit(self.url).hostname or self.url

    @property
    def thin(self) -> bool:
        """Little server-rendered text (typical for JavaScript-only single-page apps)."""
        return len(self.text) < THIN_TEXT

    def as_text(self) -> str:
        lines = [f"Website: {self.url}"]
        if self.title:
            lines.append(f"Title: {self.title}")
        if self.description:
            lines.append(f"Description: {self.description}")
        if self.headings:
            lines.append("Headings: " + " | ".join(self.headings))
        if self.pricing:
            lines.append(f"Pricing section:\n{self.pricing}")
        if self.text:
            lines.append(f"Page text:\n{self.text}")
        return "\n".join(lines)


def find_site(text: str) -> str | None:
    """First non-GitHub website link in the text, normalised to https, or None."""
    candidates: list[tuple[int, str]] = [(m.start(), m.group(0)) for m in _URL.finditer(text)]
    scheme_spans = [(m.start(), m.end()) for m in _URL.finditer(text)]
    for m in _BARE.finditer(text):
        if any(a <= m.start() < b for a, b in scheme_spans):
            continue
        if m.group(1).rsplit(".", 1)[-1].lower() in _NOT_TLDS:
            continue
        candidates.append((m.start(), "https://" + m.group(0)))
    for _, raw in sorted(candidates):
        url = raw.rstrip(".,;:!?")
        host = (urlsplit(url).hostname or "").lower()
        if host and host not in _SKIP_HOSTS and not host.endswith(".github.com"):
            return url
    return None


def _normalise(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme == "http":
        scheme = "https"
    if scheme != "https":
        raise SiteUnavailable("only http(s) website links can be read")
    if parts.username or parts.password:
        raise SiteUnavailable("links with a username or password can't be read")
    if parts.port not in (None, 443):
        raise SiteUnavailable("only websites on the standard port can be read")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise SiteUnavailable("that link has no host name")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise SiteUnavailable("give the website's name, not a bare IP address")
    return urlunsplit((scheme, host, parts.path or "/", parts.query, ""))


async def _public_address(host: str, resolver: Resolver) -> str:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise SiteUnavailable("give the website's name, not a bare IP address")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise SiteUnavailable(f"{host} isn't a public website")
    try:
        addresses = await resolver(host)
    except OSError as exc:
        raise SiteUnavailable(f"{host} doesn't exist (DNS lookup failed)") from exc
    if not addresses:
        raise SiteUnavailable(f"{host} doesn't exist (DNS lookup failed)")
    if not all(_is_public(a) for a in addresses):
        raise SiteUnavailable(f"{host} isn't a public website")
    return addresses[0]


async def _pinned_get(
    client: httpx.AsyncClient, url: str, resolver: Resolver, *, accept: str
) -> tuple[int, dict[str, str], bytes]:
    """GET ``url`` on the checked address; returns status, headers and at most MAX_BYTES of body."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    ip = await _public_address(host, resolver)
    netloc = f"[{ip}]" if ":" in ip else ip
    target = urlunsplit(("https", netloc, parts.path or "/", parts.query, ""))
    headers = {"Host": host, "User-Agent": DEFAULT_UA, "Accept": accept, "Accept-Encoding": "gzip, deflate"}
    try:
        async with client.stream("GET", target, headers=headers, extensions={"sni_hostname": host}) as res:
            body = bytearray()
            async for chunk in res.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    break
            return res.status_code, {k.lower(): v for k, v in res.headers.items()}, bytes(body[:MAX_BYTES])
    except httpx.TimeoutException as exc:
        raise SiteUnavailable(f"{host} took too long to answer") from exc
    except httpx.HTTPError as exc:
        raise SiteUnavailable(f"couldn't connect to {host}") from exc


async def _robots_allow(client: httpx.AsyncClient, url: str, resolver: Resolver) -> bool:
    parts = urlsplit(url)
    robots = urlunsplit(("https", parts.netloc, "/robots.txt", "", ""))
    try:
        status, _, body = await _pinned_get(client, robots, resolver, accept="text/plain")
    except SiteUnavailable:
        return True  # unreachable robots.txt: no rule against us (the page fetch is still guarded)
    if status >= 400:
        return True
    parser = RobotFileParser()
    parser.parse(body.decode("utf-8", "replace").splitlines())
    return parser.can_fetch(ROBOTS_TOKEN, url)


def _clean(text: str) -> str:
    text = _WS.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return _LINES.sub("\n\n", text).strip()


def _meta(tree: HTMLParser, *names: str) -> str:
    for name in names:
        node = tree.css_first(f'meta[name="{name}"]') or tree.css_first(f'meta[property="{name}"]')
        if node and (content := (node.attributes.get("content") or "").strip()):
            return content[:500]
    return ""


def extract(html: str, url: str) -> SiteFacts:
    tree = HTMLParser(html)
    title_node = tree.css_first("title")
    title = _meta(tree, "og:title") or (title_node.text(strip=True)[:200] if title_node else "")
    description = _meta(tree, "description", "og:description", "twitter:description")
    for node in tree.css(_DROP):
        node.decompose()
    headings: list[str] = []
    for node in tree.css("h1, h2, h3"):
        h = " ".join(node.text(separator=" ", strip=True).split())
        if h and h not in headings:
            headings.append(h[:160])
        if len(headings) >= 20:
            break
    pricing = ""
    for node in tree.css("[id], [class]"):
        marker = f"{node.attributes.get('id') or ''} {node.attributes.get('class') or ''}".lower()
        if "pricing" in marker or "plans" in marker:
            pricing = _clean(node.text(separator="\n"))[:1500]
            if pricing:
                break
    body = tree.css_first("main") or tree.body
    text = _clean(body.text(separator="\n")) if body else ""
    if len(text) > TEXT_LIMIT:
        text = text[:TEXT_LIMIT].rsplit("\n", 1)[0] + "\n…(page text truncated)"
    return SiteFacts(url=url, title=title, description=description, headings=headings, pricing=pricing, text=text)


async def fetch_site(
    url: str,
    *,
    resolver: Resolver = system_resolver,
    transport: httpx.AsyncBaseTransport | None = None,
    request_timeout_s: float = 10.0,
) -> SiteFacts:
    current = _normalise(url)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(request_timeout_s, connect=5.0), follow_redirects=False, transport=transport
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            if not await _robots_allow(client, current, resolver):
                raise SiteUnavailable(f"{urlsplit(current).hostname} asks automated readers not to read this page")
            status, headers, body = await _pinned_get(
                client, current, resolver, accept="text/html,application/xhtml+xml;q=0.9,*/*;q=0.1"
            )
            if status in (301, 302, 303, 307, 308) and headers.get("location"):
                current = _normalise(urljoin(current, headers["location"]))
                continue
            if status in (401, 403):
                raise SiteUnavailable(f"{urlsplit(current).hostname} refused the request ({status})")
            if status == 404:
                raise SiteUnavailable("that page doesn't exist (404)")
            if status >= 400:
                raise SiteUnavailable(f"{urlsplit(current).hostname} answered {status}")
            ctype = headers.get("content-type", "")
            if "html" not in ctype:
                raise SiteUnavailable("that link isn't a web page (not HTML)")
            charset = "utf-8"
            if m := re.search(r"charset=([\w-]+)", ctype, re.IGNORECASE):
                charset = m.group(1)
            try:
                html = body.decode(charset, "replace")
            except LookupError:
                html = body.decode("utf-8", "replace")
            return extract(html, current)
    raise SiteUnavailable("too many redirects")
