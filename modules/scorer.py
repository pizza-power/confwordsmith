"""Weighted scoring engine for ranking candidate token quality."""

from __future__ import annotations

import json
import logging
from typing import Any

from .storage import Storage
from .utils import shannon_entropy

logger = logging.getLogger("confwordsmith.scorer")


def score_all_tokens(storage: Storage, cfg: dict[str, Any]) -> None:
    """Compute and persist scores for every token in the database."""
    sc = cfg.get("scoring", {})
    tokens = storage.get_all_tokens()
    logger.info("Scoring %d tokens", len(tokens))

    max_freq = max((t["frequency"] for t in tokens), default=1)

    for t in tokens:
        score = _compute_score(t, sc, max_freq)
        storage.update_token_score(t["token"], score)

    logger.info("Scoring complete")


def _compute_score(
    t: dict[str, Any],
    sc: dict[str, Any],
    max_freq: int,
) -> float:
    score = 0.0
    freq = t["frequency"]

    if t.get("in_title"):
        score += sc.get("title_weight", 3.0)

    contexts = json.loads(t.get("contexts", "[]")) if isinstance(t.get("contexts"), str) else t.get("contexts", [])
    if any(c == "heading" for c in contexts):
        score += sc.get("heading_weight", 2.5)

    norm_freq = freq / max_freq if max_freq > 0 else 0
    score += norm_freq * sc.get("frequency_weight", 1.5)

    space_count = t.get("space_count", 1)
    if space_count > 1:
        score += min(space_count, 5) * sc.get("multi_space_weight", 2.0) * 0.5

    if t.get("is_camel"):
        score += sc.get("camelcase_weight", 1.5)

    if t.get("is_acronym"):
        score += sc.get("acronym_weight", 2.0)

    token = t["token"]
    if any(c.isdigit() for c in token) and any(c.isalpha() for c in token):
        score += sc.get("alphanumeric_weight", 1.2)

    length = len(token)
    if length < 4:
        score *= sc.get("length_penalty_short", 0.5)
    elif length > 30:
        score *= sc.get("length_penalty_long", 0.8)
    elif 6 <= length <= 16:
        score += 0.5

    if t.get("dict_match"):
        score *= sc.get("dictionary_penalty", 0.3)

    entropy = t.get("entropy", 0.0)
    if entropy > 4.5:
        score *= 0.7
    elif entropy < 2.0 and length > 4:
        score *= 0.9

    score = round(max(score, 0.0), 4)
    return score
