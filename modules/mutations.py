"""Password candidate mutation generator with configurable profiles."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger("confwordsmith.mutations")

# Profile definitions: (years, numeric_suffixes, symbol_suffixes, do_case_variants, do_seasons, do_separators)
PROFILES: dict[str, dict[str, bool]] = {
    "minimal": {
        "years": True,
        "numerics": False,
        "symbols": True,
        "case_variants": False,
        "seasons": False,
        "separators": False,
        "year_symbol_combo": False,
    },
    "balanced": {
        "years": True,
        "numerics": True,
        "symbols": True,
        "case_variants": True,
        "seasons": False,
        "separators": False,
        "year_symbol_combo": True,
    },
    "aggressive": {
        "years": True,
        "numerics": True,
        "symbols": True,
        "case_variants": True,
        "seasons": True,
        "separators": True,
        "year_symbol_combo": True,
    },
}


def generate_mutations(
    tokens: list[str],
    cfg: dict[str, Any],
) -> list[str]:
    """Generate mutated password candidates from high-quality tokens."""
    mut_cfg = cfg.get("mutations", {})
    profile_name = mut_cfg.get("profile", "balanced")
    profile = PROFILES.get(profile_name, PROFILES["balanced"])

    years = _build_years(mut_cfg)
    numerics = mut_cfg.get("numeric_suffixes", ["1", "12", "123", "1234", "01", "99"])
    symbols = mut_cfg.get("symbol_suffixes", ["!", "@", "#", "$", "!!"])
    seasons = mut_cfg.get("seasons", ["Spring", "Summer", "Fall", "Winter"])
    separators = mut_cfg.get("separators", ["", "_", "-", "."])

    candidates: set[str] = set()

    for base in tokens:
        candidates.add(base)

        if profile["years"]:
            for y in years:
                candidates.add(f"{base}{y}")
                if profile["year_symbol_combo"]:
                    for sym in symbols:
                        candidates.add(f"{base}{y}{sym}")

        if profile["numerics"]:
            for n in numerics:
                candidates.add(f"{base}{n}")
                for sym in symbols:
                    candidates.add(f"{base}{n}{sym}")

        if profile["symbols"]:
            for sym in symbols:
                candidates.add(f"{base}{sym}")

        if profile["case_variants"]:
            candidates.add(base.lower())
            candidates.add(base.upper())
            candidates.add(base.capitalize())
            if len(base) > 1:
                candidates.add(base[0].lower() + base[1:])

        if profile["seasons"]:
            for season in seasons:
                candidates.add(f"{base}{season}")
                for y in years:
                    candidates.add(f"{base}{season}{y}")
                    if profile["year_symbol_combo"]:
                        for sym in symbols:
                            candidates.add(f"{base}{season}{y}{sym}")

        if profile["separators"] and len(separators) > 1:
            for sep in separators:
                if not sep:
                    continue
                for y in years:
                    candidates.add(f"{base}{sep}{y}")
                for n in numerics:
                    candidates.add(f"{base}{sep}{n}")

    logger.info(
        "Generated %d mutations from %d base tokens (profile: %s)",
        len(candidates), len(tokens), profile_name,
    )
    return sorted(candidates)


def _build_years(mut_cfg: dict[str, Any]) -> list[str]:
    years_raw = list(mut_cfg.get("years", [2024, 2025, 2026]))
    if mut_cfg.get("use_current_year", True):
        current = datetime.now().year
        if current not in years_raw:
            years_raw.append(current)
    years_raw.sort()
    result: list[str] = []
    for y in years_raw:
        full = str(y)
        short = full[-2:]
        if full not in result:
            result.append(full)
        if short not in result:
            result.append(short)
    return result
