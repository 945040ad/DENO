"""Normalisation, boilerplate stripping, language check and chunking."""

from __future__ import annotations

import re
import unicodedata

from langchain_text_splitters import RecursiveCharacterTextSplitter

from deno_sources.normalize import clean_text

CHUNK_TOKENS = 400
CHUNK_OVERLAP = 60
SINGLE_CHUNK_TOKENS = 480  # posts up to this size stay whole

_BOILERPLATE = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"^\s*(\[deleted\]|\[removed\])\s*$",
        r"^\s*(edit|update)\s*\d*\s*:.*$",
        r"^\s*(follow|subscribe to) (me|us)\b.*$",
        r"^\s*(sent from my \w+)\s*$",
        r"^\s*(view|see) (the )?(original|full) (post|thread)\b.*$",
        r"^\s*#\w+(\s+#\w+)*\s*$",  # a line of hashtags only
        r"^\s*pic\.twitter\.com/\S+\s*$",
        r"^\s*https?://t\.co/\S+\s*$",
    )
]
_URL = re.compile(r"https?://\S+")
_WORD = re.compile(r"[a-z']+")
# Frequent English function words; a real post almost always contains several.
_EN_STOPWORDS = frozenset(
    [
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "to",
        "of",
        "in",
        "on",
        "for",
        "with",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "it",
        "this",
        "that",
        "i",
        "you",
        "we",
        "they",
        "my",
        "our",
        "your",
        "not",
        "no",
        "so",
        "if",
        "at",
        "as",
        "by",
        "from",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "can",
        "could",
        "would",
        "should",
        "will",
        "just",
        "about",
        "what",
        "how",
        "when",
        "why",
        "who",
        "which",
        "there",
        "their",
        "them",
        "me",
        "he",
        "she",
        "his",
        "her",
        "its",
        "than",
        "then",
        "too",
        "very",
        "really",
    ]
)


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", clean_text(text))
    kept = [line for line in text.split("\n") if not any(p.match(line) for p in _BOILERPLATE)]
    return "\n".join(kept).strip()


def approx_tokens(text: str) -> int:
    """~4 characters per token for English; no tokenizer download needed."""
    return (len(text) + 3) // 4


def is_english(text: str, *, min_ratio: float = 0.12) -> bool:
    """Cheap language gate: enough ASCII letters and enough English function words.

    Short texts (< 6 words) pass, since there isn't enough signal and the analysts can ignore them.
    """
    stripped = _URL.sub(" ", text)
    letters = [c for c in stripped if c.isalpha()]
    if letters and sum(c.isascii() for c in letters) / len(letters) < 0.8:
        return False
    words = _WORD.findall(stripped.lower())
    if len(words) < 6:
        return True
    return sum(w in _EN_STOPWORDS for w in words) / len(words) >= min_ratio


_splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_TOKENS,
    chunk_overlap=CHUNK_OVERLAP,
    length_function=approx_tokens,
    separators=["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ", ""],
    keep_separator="end",
)


def chunk(text: str) -> list[str]:
    """Posts stay whole; long threads/articles split at ~400 tokens with ~60 overlap."""
    if approx_tokens(text) <= SINGLE_CHUNK_TOKENS:
        return [text] if text else []
    return [c.strip() for c in _splitter.split_text(text) if c.strip()]
