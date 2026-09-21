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
