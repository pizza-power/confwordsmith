"""Scan extracted page content for potential plaintext credentials."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("confwordsmith.credscanner")


@dataclass
class CredentialFind:
    """A single potential credential extracted from a page."""
    value: str
    pattern_name: str
    context_type: str
    surrounding_text: str
    space_key: str
    page_id: str
    page_title: str
    confidence: str  # high, medium, low


# Key-value assignments: password = "foo", secret: bar, etc.
_RE_KV_ASSIGN = re.compile(
    r"""(?:password|passwd|pwd|pass|secret|token|apikey|api_key|api[-_]?secret"""
    r"""|auth|credential|private[-_]?key|access[-_]?key|conn(?:ection)?[-_]?(?:str|string))"""
    r"""\s*[:=]\s*["']?([^\s"',;}{)(\]\[]{3,})""",
    re.IGNORECASE,
)

# Environment variable style: export DB_PASS="value"
_RE_ENV_VAR = re.compile(
    r"""(?:export\s+)?\w*(?:PASS(?:WORD|WD)?|SECRET|TOKEN|KEY|CREDENTIAL|AUTH)"""
    r"""\w*\s*=\s*["']?([^\s"',;}{)(\]\[]{3,})""",
    re.IGNORECASE,
)

# Connection strings: scheme://user:password@host
_RE_CONN_STRING = re.compile(
    r"""(?:jdbc:|mongodb(?:\+srv)?:|mysql:|postgres(?:ql)?:|redis:|amqp:|"""
    r"""ftp|ssh|https?)://[^:]+:([^@\s"']{3,})@""",
    re.IGNORECASE,
)

# Inline "default password is X" / "credentials: admin / X"
_RE_INLINE_CRED = re.compile(
    r"""(?:default\s+(?:password|cred(?:ential)?s?)|"""
    r"""(?:password|pwd|pass)\s+(?:is|was|are|set\s+to))\s*[:\s]?\s*["']?"""
    r"""([^\s"',;}{)(\]\[]{3,})""",
    re.IGNORECASE,
)

# "user / password" or "user:password" patterns near credential keywords
_RE_SLASH_PAIR = re.compile(
    r"""(?:login|cred(?:ential)?s?|account|user)\s*[:=]?\s*\S+\s*[/\\|]\s*([^\s"',;}{)(\]\[]{3,})""",
    re.IGNORECASE,
)

# Bearer/Basic token headers
_RE_AUTH_HEADER = re.compile(
    r"""(?:Authorization|Bearer|Basic)\s*[:=]?\s*["']?((?:Bearer\s+)?[A-Za-z0-9_\-.+/=]{20,})""",
    re.IGNORECASE,
)

_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("key_value_assign", _RE_KV_ASSIGN, "high"),
    ("env_variable", _RE_ENV_VAR, "high"),
    ("connection_string", _RE_CONN_STRING, "high"),
    ("inline_credential", _RE_INLINE_CRED, "medium"),
    ("slash_pair", _RE_SLASH_PAIR, "medium"),
    ("auth_header", _RE_AUTH_HEADER, "medium"),
]

# Values that are clearly placeholders, not real credentials
_PLACEHOLDER_PATTERNS = re.compile(
    r"""^(?:xxx+|your[-_]?(?:password|token|key|secret)|changeme|placeholder|"""
    r"""TODO|FIXME|example|replace[-_]?me|insert[-_]?here|none|null|empty|"""
    r"""<[^>]+>|\$\{[^}]+\}|\{\{[^}]+\}\}|%[^%]+%)$""",
    re.IGNORECASE,
)


def _is_placeholder(value: str) -> bool:
    """Filter out obvious placeholder values."""
    if _PLACEHOLDER_PATTERNS.match(value):
        return True
    if value.startswith("$") or value.startswith("{"):
        return True
    if all(c == c.upper() and c.isalpha() for c in value if c.isalpha()) and "_" in value:
        # ALL_CAPS_WITH_UNDERSCORES is likely a variable name, not a password
        if not any(c.isdigit() for c in value) and len(value) > 10:
            return True
    return False


def _truncate(text: str, max_len: int = 120) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def scan_page_for_credentials(
    page_content: Any,
    page_title: str = "",
) -> list[CredentialFind]:
    """
    Scan all text segments of a PageContent for potential credentials.

    Returns a list of CredentialFind objects.
    """
    space_key = page_content.space_key
    page_id = page_content.page_id
    title = page_title or page_content.title

    segments: list[tuple[str, str]] = []

    for code in page_content.code_blocks:
        segments.append((code, "code_block"))
    for ic in page_content.inline_code:
        segments.append((ic, "inline_code"))
    for tc in page_content.table_cells:
        segments.append((tc, "table_cell"))
    for p in page_content.paragraphs:
        segments.append((p, "paragraph"))
    for li in page_content.list_items:
        segments.append((li, "list_item"))
    for h in page_content.headings:
        segments.append((h, "heading"))

    finds: list[CredentialFind] = []
    seen_values: set[str] = set()

    for text, context_type in segments:
        if not text or len(text) < 5:
            continue

        for pattern_name, pattern, base_confidence in _PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(1).strip().rstrip("\"'.,;:")
                if not value or len(value) < 3:
                    continue
                if _is_placeholder(value):
                    continue

                # Boost confidence for code blocks / inline code
                confidence = base_confidence
                if context_type in ("code_block", "inline_code") and confidence == "medium":
                    confidence = "high"

                dedup_key = f"{value}|{space_key}|{page_id}"
                if dedup_key in seen_values:
                    continue
                seen_values.add(dedup_key)

                finds.append(CredentialFind(
                    value=value,
                    pattern_name=pattern_name,
                    context_type=context_type,
                    surrounding_text=_truncate(text),
                    space_key=space_key,
                    page_id=page_id,
                    page_title=title,
                    confidence=confidence,
                ))

    return finds


def scan_table_adjacency(
    page_content: Any,
    page_title: str = "",
) -> list[CredentialFind]:
    """
    Look for table rows where one cell contains a credential keyword
    and an adjacent cell contains a potential value.
    """
    # This requires the raw HTML which we don't have at this stage,
    # but table_cells are extracted in order, so adjacent cells are
    # sequential in the list. Check pairs.
    space_key = page_content.space_key
    page_id = page_content.page_id
    title = page_title or page_content.title

    keyword_re = re.compile(
        r"(?:password|passwd|pwd|secret|token|key|credential|pass)",
        re.IGNORECASE,
    )

    finds: list[CredentialFind] = []
    cells = page_content.table_cells

    for i, cell in enumerate(cells):
        if not keyword_re.search(cell):
            continue
        # Check the next cell as the potential value
        if i + 1 < len(cells):
            candidate = cells[i + 1].strip()
            if candidate and 3 <= len(candidate) <= 128 and not keyword_re.match(candidate):
                if not _is_placeholder(candidate):
                    finds.append(CredentialFind(
                        value=candidate,
                        pattern_name="table_adjacency",
                        context_type="table_cell",
                        surrounding_text=f"{cell} | {candidate}",
                        space_key=space_key,
                        page_id=page_id,
                        page_title=title,
                        confidence="medium",
                    ))

    return finds


def format_credential_line(find: CredentialFind) -> str:
    """Format a credential find for the output file."""
    return (
        f"[{find.confidence.upper()}] [{find.pattern_name}] "
        f"Space={find.space_key} Page=\"{find.page_title}\" "
        f"Context={find.context_type} Value={find.value}"
    )
