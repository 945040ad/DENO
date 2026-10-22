"""URL canonicalisation, content hashing and text hygiene for scraped content."""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PARAMS = {
    "s",
    "t",
    "ref",
    "ref_src",
    "ref_url",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "trk",
    "trackingId",
    "lipi",
    "fbclid",
    "gclid",
    "igshid",
    "si",
    "rcm",
    "share_id",
}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ud800-\udfff]")
_TAG = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[ \t ]+")
_BLANK_LINES = re.compile(r"\n{3,}")

X_HOSTS = {"x.com", "twitter.com", "mobile.twitter.com", "www.twitter.com", "www.x.com", "mobile.x.com"}


def canonical_url(url: str) -> str:
    """Stable identity for dedupe: https, lowercase host, no tracking params/fragment, x.com for tweets."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if host in X_HOSTS:
        host = "x.com"
    elif host.endswith(".linkedin.com"):
        host = "www.linkedin.com"
    elif host in {"old.reddit.com", "np.reddit.com", "reddit.com"}:
        host = "www.reddit.com"
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if k not in _TRACKING_PARAMS])
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", host, path, query, ""))


def clean_text(value: str) -> str:
    """Plain text from possibly-HTML, entity-encoded, control-character-laden input."""
    text = html.unescape(_TAG.sub(" ", value.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")))
    text = _CONTROL.sub("", unicodedata.normalize("NFC", text))
    lines = [_SPACES.sub(" ", line).strip() for line in text.replace("\r\n", "\n").split("\n")]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def content_hash(text: str) -> str:
    """Hash of the whitespace/case-normalised text, to spot the same post under different URLs."""
    normalised = " ".join(clean_text(text).lower().split())
    return hashlib.sha256(normalised.encode()).hexdigest()


_WORD = re.compile(r"[a-z0-9]+")
_QUERY_STOP = frozenset(
    [
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "your",
        "you",
        "are",
        "how",
        "what",
        "why",
        "who",
        "into",
        "about",
        "tool",
        "tools",
        "app",
        "apps",
        "software",
    ]
)


def distinctive_terms(query: str) -> list[str]:
    """The words of a query worth searching for: lowercase, no stop words, no 1-2 letter words."""
    return list(dict.fromkeys(t for t in _WORD.findall(query.lower()) if t not in _QUERY_STOP and len(t) > 2))


def query_stems(query: str) -> list[str]:
    """Distinctive words of a search query, cut to 5-letter stems so "tracking" matches "tracker"."""
    return list(dict.fromkeys(t[:5] for t in distinctive_terms(query)))


def mentions_near(text: str, stems: list[str], window: int = 12) -> bool:
    """True when every stem appears within ``window`` words of the others.

    Search APIs match words anywhere in a long comment, so "posture analysis" also returns a thread about
    "security posture" that says "analysis" three paragraphs later. Requiring the words close together
    keeps posts that actually talk about the thing searched for."""
    if not stems:
        return False
    words = _WORD.findall(text.lower())
    hits = [(i, s) for i, w in enumerate(words) for s in stems if w.startswith(s)]
    if len(stems) == 1:
        return bool(hits)
    for i, first in hits:
        nearby = {s for j, s in hits if abs(j - i) <= window}
        if first in nearby and nearby >= set(stems):
            return True
    return False
