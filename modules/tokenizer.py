"""Tokenizer that splits text while preserving enterprise naming conventions."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("confwordsmith.tokenizer")

# Pre-compiled patterns
_RE_CAMELCASE_SPLIT = re.compile(
    r"(?<=[a-z])(?=[A-Z])"          # aB -> a | B
    r"|(?<=[A-Z])(?=[A-Z][a-z])"    # ABc -> A | Bc
)
_RE_SEPARATOR_SPLIT = re.compile(r"[_\-./\\]+")
_RE_WORD_BOUNDARY = re.compile(r"[\s,;:!?\[\](){}<>\"\'`|=+*/&^%$@~]+")
_RE_ALLCAPS = re.compile(r"^[A-Z][A-Z0-9]{1,}$")
_RE_CAMELCASE = re.compile(r"^[A-Z][a-z]+(?:[A-Z][a-z0-9]*)+$")
_RE_MIXED_ALNUM = re.compile(r"^(?=.*[A-Za-z])(?=.*[0-9])[A-Za-z0-9]+$")
_RE_HOSTNAME = re.compile(
    r"^[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?){1,}$"
)


def tokenize_text(text: str, cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """
    Split text into candidate tokens, returning metadata for each.

    Returns list of dicts:
        {"token": str, "is_acronym": bool, "is_camel": bool, "original": str}
    """
    cfg = cfg or {}
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    raw_tokens = _RE_WORD_BOUNDARY.split(text)

    for raw in raw_tokens:
        raw = raw.strip()
        if not raw:
            continue

        _emit(raw, raw, results, seen)

        if _RE_HOSTNAME.match(raw) and "." in raw:
            for part in raw.split("."):
                if part:
                    _emit(part, raw, results, seen)

        sub_parts = _RE_SEPARATOR_SPLIT.split(raw)
        if len(sub_parts) > 1:
            joined = "".join(sub_parts)
            _emit(joined, raw, results, seen)
            for sp in sub_parts:
                if sp:
                    _emit(sp, raw, results, seen)

        camel_parts = _split_camelcase(raw)
        if len(camel_parts) > 1:
            for cp in camel_parts:
                _emit(cp, raw, results, seen)
            for i in range(len(camel_parts) - 1):
                combined = camel_parts[i] + camel_parts[i + 1]
                _emit(combined, raw, results, seen)

    return results


def _emit(
    token: str,
    original: str,
    results: list[dict[str, Any]],
    seen: set[str],
) -> None:
    """Add a token to results if not already seen."""
    token = token.strip(".")
    if not token or token in seen:
        return
    seen.add(token)
    results.append({
        "token": token,
        "is_acronym": bool(_RE_ALLCAPS.match(token)),
        "is_camel": bool(_RE_CAMELCASE.match(token)),
        "is_mixed_alnum": bool(_RE_MIXED_ALNUM.match(token)),
        "original": original,
    })


def _split_camelcase(s: str) -> list[str]:
    """Split CamelCase while keeping consecutive uppercase as one unit."""
    parts = _RE_CAMELCASE_SPLIT.split(s)
    return [p for p in parts if p]


def classify_token(token: str) -> dict[str, bool]:
    """Return boolean flags classifying a single token."""
    return {
        "is_acronym": bool(_RE_ALLCAPS.match(token)),
        "is_camel": bool(_RE_CAMELCASE.match(token)),
        "is_mixed_alnum": bool(_RE_MIXED_ALNUM.match(token)),
        "is_hostname": bool(_RE_HOSTNAME.match(token)),
        "has_digits": bool(re.search(r"\d", token)),
    }
