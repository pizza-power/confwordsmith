"""Utility functions: config loading, logging setup, and shared helpers."""

from __future__ import annotations

import logging
import math
import os
import sys
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"

DEFAULT_STOPWORDS: set[str] = {
    "the", "be", "to", "of", "and", "a", "in", "that", "have", "i",
    "it", "for", "not", "on", "with", "he", "as", "you", "do", "at",
    "this", "but", "his", "by", "from", "they", "we", "say", "her",
    "she", "or", "an", "will", "my", "one", "all", "would", "there",
    "their", "what", "so", "up", "out", "if", "about", "who", "get",
    "which", "go", "me", "when", "make", "can", "like", "time", "no",
    "just", "him", "know", "take", "people", "into", "year", "your",
    "good", "some", "could", "them", "see", "other", "than", "then",
    "now", "look", "only", "come", "its", "over", "think", "also",
    "back", "after", "use", "two", "how", "our", "work", "first",
    "well", "way", "even", "new", "want", "because", "any", "these",
    "give", "day", "most", "us", "are", "was", "were", "been", "has",
    "had", "did", "does", "may", "should", "shall", "must", "need",
    "here", "there", "where", "why", "how", "each", "every", "both",
    "few", "more", "many", "such", "own", "same", "too", "very",
    "page", "content", "table", "section", "click", "view", "edit",
    "space", "confluence", "wiki", "created", "updated", "version",
    "null", "undefined", "true", "false", "none", "todo", "fixme",
}


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load YAML configuration, falling back to defaults for missing keys."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
    else:
        cfg = {}
    return cfg


def merge_cli_into_config(cfg: dict[str, Any], args: Any) -> dict[str, Any]:
    """Override config values with CLI arguments when provided."""
    if getattr(args, "url", None):
        cfg.setdefault("confluence", {})["url"] = args.url
    if getattr(args, "token", None):
        cfg.setdefault("confluence", {})["token"] = args.token
    if getattr(args, "spaces", None):
        cfg.setdefault("spaces", {})["include"] = [
            s.strip() for s in args.spaces.split(",") if s.strip()
        ]
    if getattr(args, "output", None):
        cfg.setdefault("output", {})["directory"] = args.output
    if getattr(args, "min_length", None) is not None:
        cfg.setdefault("filters", {})["min_length"] = args.min_length
    if getattr(args, "threads", None) is not None:
        cfg.setdefault("confluence", {})["threads"] = args.threads
    if getattr(args, "proxy", None):
        cfg.setdefault("confluence", {})["proxy"] = args.proxy
    if getattr(args, "verify_ssl", None) is not None:
        cfg.setdefault("confluence", {})["verify_ssl"] = args.verify_ssl
    if getattr(args, "exclude_regex", None):
        cfg.setdefault("filters", {})["exclude_regex"] = args.exclude_regex
    if getattr(args, "dictionary", None):
        cfg.setdefault("dictionary", {})["paths"] = args.dictionary
    if getattr(args, "cache_db", None):
        cfg.setdefault("cache", {})["database"] = args.cache_db
    if getattr(args, "mutations", None):
        cfg.setdefault("mutations", {})["profile"] = args.mutations
    if getattr(args, "verbose", False):
        cfg.setdefault("logging", {})["level"] = "DEBUG"
    return cfg


def setup_logging(cfg: dict[str, Any]) -> logging.Logger:
    """Configure structured logging to file and stderr."""
    log_cfg = cfg.get("logging", {})
    level_name = log_cfg.get("level", "INFO").upper()
    log_file = log_cfg.get("file", "./logs/confwordsmith.log")

    log_dir = Path(log_file).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("confwordsmith")
    logger.setLevel(getattr(logging, level_name, logging.INFO))
    logger.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(getattr(logging, level_name, logging.INFO))
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    console_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(message)s",
        datefmt="%H:%M:%S",
    )
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(getattr(logging, level_name, logging.INFO))
    sh.setFormatter(console_fmt)
    logger.addHandler(sh)

    return logger


def get_stopwords(cfg: dict[str, Any]) -> set[str]:
    """Build the effective stopword set from config."""
    sw_cfg = cfg.get("stopwords", {})
    words: set[str] = set()
    if sw_cfg.get("use_default", True):
        words |= DEFAULT_STOPWORDS
    for w in sw_cfg.get("custom", []):
        words.add(w.lower())
    return words


def shannon_entropy(s: str) -> float:
    """Calculate Shannon entropy of a string."""
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    length = len(s)
    return -sum(
        (c / length) * math.log2(c / length) for c in freq.values()
    )


def ensure_dirs(cfg: dict[str, Any]) -> None:
    """Create output, cache, and log directories."""
    for key_path in [
        ("output", "directory"),
        ("cache", "database"),
        ("logging", "file"),
    ]:
        section = cfg
        for k in key_path[:-1]:
            section = section.get(k, {})
        value = section.get(key_path[-1], "")
        if value:
            p = Path(value)
            target = p.parent if p.suffix else p
            target.mkdir(parents=True, exist_ok=True)
