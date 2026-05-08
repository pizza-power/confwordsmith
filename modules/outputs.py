"""Output file generation: wordlists, rules, PRINCE input, and statistics."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .mutations import generate_mutations
from .rules import generate_hashcat_rules
from .storage import Storage

logger = logging.getLogger("confwordsmith.outputs")


def write_all_outputs(
    storage: Storage,
    cfg: dict[str, Any],
) -> dict[str, str]:
    """Generate all configured output files and return path mapping."""
    out_cfg = cfg.get("output", {})
    out_dir = Path(out_cfg.get("directory", "./output"))
    out_dir.mkdir(parents=True, exist_ok=True)
    formats = out_cfg.get("formats", {})
    threshold = out_cfg.get("high_confidence_threshold", 5.0)

    all_tokens = storage.get_all_tokens()
    paths: dict[str, str] = {}

    sorted_tokens = sorted(all_tokens, key=lambda t: t["score"], reverse=True)
    token_strings = [t["token"] for t in sorted_tokens]

    if formats.get("raw_corpus", True):
        p = out_dir / "raw_corpus.txt"
        _write_lines(p, token_strings)
        paths["raw_corpus"] = str(p)

    if formats.get("cleaned_candidates", True):
        cleaned = [t["token"] for t in sorted_tokens if t["score"] > 0]
        p = out_dir / "cleaned_candidates.txt"
        _write_lines(p, cleaned)
        paths["cleaned_candidates"] = str(p)

    if formats.get("high_confidence", True):
        high = [t["token"] for t in sorted_tokens if t["score"] >= threshold]
        p = out_dir / "high_confidence.txt"
        _write_lines(p, high)
        paths["high_confidence"] = str(p)

    if formats.get("mutations", True):
        bases = [t["token"] for t in sorted_tokens if t["score"] >= threshold * 0.5]
        if not bases:
            bases = token_strings[:500]
        mutated = generate_mutations(bases, cfg)
        p = out_dir / "mutations.txt"
        _write_lines(p, mutated)
        paths["mutations"] = str(p)

    if formats.get("hashcat_rules", True):
        rules = generate_hashcat_rules(cfg)
        p = out_dir / "hashcat_rules.rule"
        _write_lines(p, rules)
        paths["hashcat_rules"] = str(p)

    if formats.get("prince_input", True):
        prince = _build_prince_input(sorted_tokens, threshold)
        p = out_dir / "prince_input.txt"
        _write_lines(p, prince)
        paths["prince_input"] = str(p)

    if formats.get("statistics", True):
        stats = _build_statistics(all_tokens, paths, cfg)
        p = out_dir / "statistics.json"
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(stats, fh, indent=2, default=str)
        paths["statistics"] = str(p)

    for name, fpath in paths.items():
        logger.info("Output: %-25s -> %s", name, fpath)

    return paths


def _write_lines(path: Path, lines: list[str]) -> None:
    seen: set[str] = set()
    with open(path, "w", encoding="utf-8") as fh:
        for line in lines:
            if line not in seen:
                seen.add(line)
                fh.write(line + "\n")


def _build_prince_input(
    sorted_tokens: list[dict[str, Any]],
    threshold: float,
) -> list[str]:
    """
    PRINCE wordlist: short high-value tokens that combine well.
    Biased toward 4-12 char tokens for combinatorial attacks.
    """
    candidates = [
        t["token"]
        for t in sorted_tokens
        if t["score"] >= threshold * 0.3 and 3 <= len(t["token"]) <= 14
    ]
    if not candidates:
        candidates = [
            t["token"] for t in sorted_tokens
            if 3 <= len(t["token"]) <= 14
        ][:1000]
    return candidates


def _build_statistics(
    all_tokens: list[dict[str, Any]],
    paths: dict[str, str],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    total = len(all_tokens)
    if total == 0:
        return {"total_tokens": 0}

    scores = [t["score"] for t in all_tokens]
    freqs = [t["frequency"] for t in all_tokens]
    acronyms = sum(1 for t in all_tokens if t.get("is_acronym"))
    camels = sum(1 for t in all_tokens if t.get("is_camel"))
    dict_matches = sum(1 for t in all_tokens if t.get("dict_match"))

    threshold = cfg.get("output", {}).get("high_confidence_threshold", 5.0)
    high_conf = sum(1 for t in all_tokens if t["score"] >= threshold)

    file_stats: dict[str, int] = {}
    for name, fpath in paths.items():
        if name == "statistics":
            continue
        try:
            with open(fpath, "r", encoding="utf-8") as fh:
                file_stats[name] = sum(1 for _ in fh)
        except OSError:
            file_stats[name] = 0

    top_tokens = [
        {"token": t["token"], "score": t["score"], "frequency": t["frequency"]}
        for t in sorted(all_tokens, key=lambda x: x["score"], reverse=True)[:50]
    ]

    return {
        "total_tokens": total,
        "high_confidence_count": high_conf,
        "acronym_count": acronyms,
        "camelcase_count": camels,
        "dictionary_matches": dict_matches,
        "score_max": round(max(scores), 4),
        "score_mean": round(sum(scores) / total, 4),
        "score_median": round(sorted(scores)[total // 2], 4),
        "frequency_max": max(freqs),
        "frequency_mean": round(sum(freqs) / total, 2),
        "output_files": file_stats,
        "top_tokens": top_tokens,
        "config_profile": cfg.get("mutations", {}).get("profile", "balanced"),
    }
