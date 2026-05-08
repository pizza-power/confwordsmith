"""Extract structured text segments from Confluence HTML storage format."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger("confwordsmith.extractor")


@dataclass
class PageContent:
    """Structured extraction result for a single Confluence page."""
    page_id: str = ""
    space_key: str = ""
    title: str = ""
    author: str = ""
    labels: list[str] = field(default_factory=list)
    attachments: list[str] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)
    table_cells: list[str] = field(default_factory=list)
    code_blocks: list[str] = field(default_factory=list)
    inline_code: list[str] = field(default_factory=list)
    list_items: list[str] = field(default_factory=list)
    link_texts: list[str] = field(default_factory=list)


def extract_page(page_data: dict[str, Any]) -> PageContent:
    """Parse a fetched page dict into structured PageContent."""
    pc = PageContent(
        page_id=page_data.get("page_id", ""),
        space_key=page_data.get("space_key", ""),
        title=page_data.get("title", ""),
        author=page_data.get("author", ""),
        labels=page_data.get("labels", []),
        attachments=page_data.get("attachments", []),
    )

    body_html = page_data.get("body_html", "")
    if not body_html:
        return pc

    try:
        soup = BeautifulSoup(body_html, "lxml")
    except Exception:
        soup = BeautifulSoup(body_html, "html.parser")

    _extract_headings(soup, pc)
    _extract_tables(soup, pc)
    _extract_code(soup, pc)
    _extract_lists(soup, pc)
    _extract_links(soup, pc)
    _extract_paragraphs(soup, pc)

    logger.debug(
        "Page %s: %d headings, %d paragraphs, %d table cells, %d code blocks",
        pc.page_id, len(pc.headings), len(pc.paragraphs),
        len(pc.table_cells), len(pc.code_blocks),
    )
    return pc


def _extract_headings(soup: BeautifulSoup, pc: PageContent) -> None:
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        text = tag.get_text(separator=" ", strip=True)
        if text:
            pc.headings.append(text)


def _extract_tables(soup: BeautifulSoup, pc: PageContent) -> None:
    for table in soup.find_all("table"):
        for cell in table.find_all(["td", "th"]):
            text = cell.get_text(separator=" ", strip=True)
            if text:
                pc.table_cells.append(text)


def _extract_code(soup: BeautifulSoup, pc: PageContent) -> None:
    for block in soup.find_all("ac:structured-macro", attrs={"ac:name": "code"}):
        body = block.find("ac:plain-text-body")
        if body:
            text = body.get_text(strip=True)
            if text:
                pc.code_blocks.append(text)

    for pre in soup.find_all("pre"):
        text = pre.get_text(strip=True)
        if text:
            pc.code_blocks.append(text)

    for code in soup.find_all("code"):
        if code.parent and code.parent.name == "pre":
            continue
        text = code.get_text(strip=True)
        if text:
            pc.inline_code.append(text)


def _extract_lists(soup: BeautifulSoup, pc: PageContent) -> None:
    for li in soup.find_all("li"):
        text = li.get_text(separator=" ", strip=True)
        if text:
            pc.list_items.append(text)


def _extract_links(soup: BeautifulSoup, pc: PageContent) -> None:
    for a in soup.find_all("a"):
        text = a.get_text(strip=True)
        if text:
            pc.link_texts.append(text)

    for link in soup.find_all("ri:page"):
        title = link.get("ri:content-title", "")
        if title:
            pc.link_texts.append(title)


def _extract_paragraphs(soup: BeautifulSoup, pc: PageContent) -> None:
    for p in soup.find_all("p"):
        text = p.get_text(separator=" ", strip=True)
        if text:
            pc.paragraphs.append(text)

    for div in soup.find_all("div"):
        if div.find("p") or div.find(["h1", "h2", "h3", "h4", "h5", "h6"]):
            continue
        text = div.get_text(separator=" ", strip=True)
        if text and len(text) > 3:
            pc.paragraphs.append(text)
