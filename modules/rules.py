"""Hashcat rule file generation for enterprise password patterns."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger("confwordsmith.rules")


def generate_hashcat_rules(cfg: dict[str, Any]) -> list[str]:
    """
    Produce Hashcat-compatible rules targeting enterprise password patterns.

    Rule syntax reference:
        :     do nothing (passthrough)
        l     lowercase all
        u     uppercase all
        c     capitalize first, lower rest
        C     lower first, upper rest
        t     toggle case of all
        $X    append character X
        ^X    prepend character X
        d     duplicate word
        r     reverse word
        TN    toggle case at position N
    """
    mut_cfg = cfg.get("mutations", {})
    years = _build_year_strings(mut_cfg)
    symbols = mut_cfg.get("symbol_suffixes", ["!", "@", "#", "$"])

    rules: list[str] = []

    # Passthrough
    rules.append(":")

    # Case rules
    rules.extend(["l", "u", "c", "C", "t"])

    # Append years
    for y in years:
        rules.append(_append_string(y))
        for sym in symbols:
            rules.append(_append_string(y + sym))

    # Append symbols
    for sym in symbols:
        rules.append(f"${sym}")

    # Append common numeric suffixes
    for n in ["1", "12", "123", "1234", "01", "99"]:
        rules.append(_append_string(n))
        for sym in symbols:
            rules.append(_append_string(n + sym))

    # Case + year combos
    for y in years:
        rules.append(f"c {_append_string(y)}")
        rules.append(f"u {_append_string(y)}")
        for sym in symbols:
            rules.append(f"c {_append_string(y + sym)}")

    # Case + symbol
    for sym in symbols:
        rules.append(f"c ${sym}")
        rules.append(f"u ${sym}")

    # Duplicate + append
    rules.append("d")
    rules.append("r")

    # Toggle position 0
    rules.append("T0")

    seen: set[str] = set()
    deduped: list[str] = []
    for r in rules:
        if r not in seen:
            seen.add(r)
            deduped.append(r)

    logger.info("Generated %d Hashcat rules", len(deduped))
    return deduped


def _append_string(s: str) -> str:
    """Build a Hashcat rule that appends each character of a string."""
    return " ".join(f"${c}" for c in s)


def _build_year_strings(mut_cfg: dict[str, Any]) -> list[str]:
    years_raw = list(mut_cfg.get("years", [2024, 2025, 2026]))
    if mut_cfg.get("use_current_year", True):
        current = datetime.now().year
        if current not in years_raw:
            years_raw.append(current)
    result: list[str] = []
    for y in sorted(set(years_raw)):
        full = str(y)
        short = full[-2:]
        result.append(full)
        if short not in result:
            result.append(short)
    return result
