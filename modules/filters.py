"""Noise filtering with configurable acronym preservation."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("confwordsmith.filters")

_common_words_cache: set[str] | None = None


def _load_common_words(path: str) -> set[str]:
    """Load a common-words file into a lowercase set, with caching."""
    global _common_words_cache
    if _common_words_cache is not None:
        return _common_words_cache
    words: set[str] = set()
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                word = line.strip()
                if word:
                    words.add(word.lower())
        logger.info("Loaded %d common words from %s", len(words), path)
    except OSError as exc:
        logger.warning("Could not read common words file %s: %s", path, exc)
    _common_words_cache = words
    return words

# Noise patterns
_RE_UUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_RE_HEX_LONG = re.compile(r"^[0-9a-fA-F]{16,}$")
_RE_HASH = re.compile(r"^[0-9a-fA-F]{32,128}$")
_RE_BASE64_BLOB = re.compile(r"^[A-Za-z0-9+/]{20,}={0,3}$")
_RE_URL = re.compile(r"^https?://", re.IGNORECASE)
_RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_RE_PURE_NUMERIC = re.compile(r"^\d+$")
_RE_MINIFIED_JS = re.compile(r"[;{}()\[\]]{3,}")
_RE_BINARY_JUNK = re.compile(r"[\x00-\x08\x0e-\x1f\x7f-\x9f]")
_RE_ALLCAPS = re.compile(r"^[A-Z][A-Z0-9]{1,}$")
_RE_CAMELCASE = re.compile(r"^[A-Z][a-z]+(?:[A-Z][a-z0-9]*)+$")
_RE_MIXED_CASE_ENTERPRISE = re.compile(r"^(?=.*[A-Z])(?=.*[a-z])[A-Za-z0-9]+$")


def filter_tokens(
    tokens: list[dict[str, Any]],
    cfg: dict[str, Any],
    stopwords: set[str],
) -> list[dict[str, Any]]:
    """Apply all noise filters, returning only viable candidates."""
    filter_cfg = cfg.get("filters", {})
    min_len = filter_cfg.get("min_length", 3)
    max_len = filter_cfg.get("max_length", 64)
    preserve_acronyms = filter_cfg.get("preserve_acronyms", True)
    acr_min = filter_cfg.get("acronym_min_length", 2)
    acr_max = filter_cfg.get("acronym_max_length", 10)
    exclude_patterns = [
        re.compile(p) for p in filter_cfg.get("exclude_regex", [])
    ]

    whitelist = set(cfg.get("whitelist", []))
    blacklist = set(cfg.get("blacklist", []))

    common_words_path = filter_cfg.get("common_words_file", "")
    common_words: set[str] = _load_common_words(common_words_path) if common_words_path else set()

    passed: list[dict[str, Any]] = []

    for entry in tokens:
        tok = entry["token"]

        if tok in whitelist:
            passed.append(entry)
            continue

        if tok in blacklist:
            logger.debug("Blacklisted: %s", tok)
            continue

        if preserve_acronyms and _is_preserved_acronym(tok, acr_min, acr_max):
            passed.append(entry)
            continue

        if len(tok) < min_len:
            continue
        if len(tok) > max_len:
            continue

        if _is_noise(tok):
            logger.debug("Filtered noise: %s", tok)
            continue

        if tok.lower() in stopwords and not _is_enterprise_term(tok):
            continue

        if common_words and tok.lower() in common_words and not _is_enterprise_term(tok):
            logger.debug("Common word filtered: %s", tok)
            continue

        excluded = False
        for pat in exclude_patterns:
            if pat.search(tok):
                excluded = True
                break
        if excluded:
            continue

        passed.append(entry)

    logger.info("Filtering: %d -> %d tokens", len(tokens), len(passed))
    return passed


def _is_preserved_acronym(tok: str, min_len: int, max_len: int) -> bool:
    """ALLCAPS acronyms within length bounds are always preserved."""
    if not _RE_ALLCAPS.match(tok):
        return False
    return min_len <= len(tok) <= max_len


def _is_enterprise_term(tok: str) -> bool:
    """Check if a token looks like an enterprise-specific term."""
    if _RE_ALLCAPS.match(tok):
        return True
    if _RE_CAMELCASE.match(tok):
        return True
    if _RE_MIXED_CASE_ENTERPRISE.match(tok) and any(c.isupper() for c in tok[1:]):
        return True
    return False


def _is_noise(tok: str) -> bool:
    """Return True if the token is structural noise or binary junk."""
    if _RE_UUID.match(tok):
        return True
    if _RE_HEX_LONG.match(tok):
        return True
    if _RE_HASH.match(tok):
        return True
    if _RE_BASE64_BLOB.match(tok) and len(tok) > 30:
        return True
    if _RE_URL.match(tok):
        return True
    if _RE_EMAIL.match(tok):
        return True
    if _RE_PURE_NUMERIC.match(tok):
        return True
    if _RE_MINIFIED_JS.search(tok):
        return True
    if _RE_BINARY_JUNK.search(tok):
        return True
    non_alnum = sum(1 for c in tok if not c.isalnum())
    if len(tok) > 5 and non_alnum / len(tok) > 0.5:
        return True
    return False


def compare_dictionary(
    tokens: list[dict[str, Any]],
    dict_paths: list[str],
    mode: str = "tag",
) -> list[dict[str, Any]]:
    """
    Compare tokens against external wordlists.

    Modes:
        remove   - drop tokens found in dictionaries (except enterprise terms)
        tag      - mark dict_match=True but keep them
        preserve - do nothing
    """
    if mode == "preserve" or not dict_paths:
        return tokens

    dict_words: set[str] = set()
    for path in dict_paths:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    word = line.strip()
                    if word:
                        dict_words.add(word.lower())
        except OSError as exc:
            logger.warning("Could not read dictionary %s: %s", path, exc)

    if not dict_words:
        return tokens

    logger.info("Loaded %d dictionary entries from %d files", len(dict_words), len(dict_paths))

    result: list[dict[str, Any]] = []
    for entry in tokens:
        tok = entry["token"]
        lower = tok.lower()
        if lower in dict_words:
            entry["dict_match"] = True
            if mode == "remove" and not _is_enterprise_term(tok):
                logger.debug("Dictionary removal: %s", tok)
                continue
        result.append(entry)

    removed = len(tokens) - len(result)
    if removed:
        logger.info("Dictionary comparison removed %d common entries", removed)
    return result
