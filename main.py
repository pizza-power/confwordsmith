#!/usr/bin/env python3
"""
confwordsmith - Enterprise password wordlist generator from Confluence content.

Generates custom cracking wordlists from Atlassian Confluence for authorized
internal security testing. Does NOT perform password attacks or cracking.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from typing import Any

from tqdm import tqdm

from modules.confluence import ConfluenceClient
from modules.credscanner import (
    CredentialFind,
    format_credential_line,
    scan_page_for_credentials,
    scan_table_adjacency,
)
from modules.extractor import PageContent, extract_page
from modules.filters import compare_dictionary, filter_tokens
from modules.outputs import write_all_outputs
from modules.scorer import score_all_tokens
from modules.storage import Storage
from modules.tokenizer import classify_token, tokenize_text
from modules.utils import (
    ensure_dirs,
    get_stopwords,
    load_config,
    merge_cli_into_config,
    setup_logging,
    shannon_entropy,
)

logger: logging.Logger


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="confwordsmith",
        description=(
            "Generate enterprise password cracking wordlists from Confluence "
            "content for authorized internal security testing."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python main.py --url https://confluence.example.com --token TOKEN\n"
            "  python main.py --url https://confluence.example.com --token TOKEN "
            "--spaces ENG,IT,HR --incremental\n"
            "  python main.py --config my_config.yaml --mutations aggressive\n"
        ),
    )
    p.add_argument("--url", help="Confluence base URL")
    p.add_argument("--token", help="Personal Access Token or API token")
    p.add_argument("--spaces", help="Comma-separated space keys to include")
    p.add_argument("--output", default=None, help="Output directory (default: ./output)")
    p.add_argument("--config", default=None, help="Path to YAML config file")
    p.add_argument(
        "--incremental", action="store_true",
        help="Only fetch pages updated since last run",
    )
    p.add_argument(
        "--mutations", choices=["aggressive", "balanced", "minimal"],
        default=None, help="Mutation generation profile",
    )
    p.add_argument("--min-length", type=int, default=None, dest="min_length",
                    help="Minimum token length (default: 3)")
    p.add_argument("--threads", type=int, default=None,
                    help="Number of threads for page retrieval")
    p.add_argument("--proxy", default=None, help="HTTP/HTTPS proxy URL")
    p.add_argument("--verify-ssl", action="store_true", default=None,
                    dest="verify_ssl", help="Verify SSL certificates")
    p.add_argument("--no-verify-ssl", action="store_false", dest="verify_ssl",
                    help="Disable SSL verification")
    p.add_argument("--exclude-regex", nargs="*", default=None,
                    help="Regex patterns to exclude tokens")
    p.add_argument("--dictionary", nargs="*", default=None,
                    help="Paths to dictionary files for comparison")
    p.add_argument("--cache-db", default=None, dest="cache_db",
                    help="Path to SQLite cache database")
    p.add_argument("--max-spaces", type=int, default=None, dest="max_spaces",
                    help="Limit number of spaces to process (0 = unlimited)")
    p.add_argument("--verbose", "-v", action="store_true",
                    help="Enable debug logging")
    return p.parse_args()


def process_page(
    page_content: PageContent,
    cfg: dict[str, Any],
    storage: Storage,
    stopwords: set[str],
) -> int:
    """Extract, tokenize, filter, and store tokens from a single page."""
    space_key = page_content.space_key
    page_id = page_content.page_id
    source_prefix = f"{space_key}:{page_id}"
    token_count = 0

    segments: list[tuple[str, str]] = []

    segments.append((page_content.title, "title"))

    for h in page_content.headings:
        segments.append((h, "heading"))

    for p in page_content.paragraphs:
        segments.append((p, "paragraph"))

    for tc in page_content.table_cells:
        segments.append((tc, "table"))

    for label in page_content.labels:
        segments.append((label, "label"))

    for att in page_content.attachments:
        segments.append((att, "attachment"))

    for code in page_content.code_blocks:
        segments.append((code, "code"))

    for ic in page_content.inline_code:
        segments.append((ic, "inline_code"))

    for li in page_content.list_items:
        segments.append((li, "list_item"))

    for lt in page_content.link_texts:
        segments.append((lt, "link"))

    if page_content.author:
        segments.append((page_content.author, "author"))

    for text, context in segments:
        raw_tokens = tokenize_text(text, cfg)
        filtered = filter_tokens(raw_tokens, cfg, stopwords)

        for entry in filtered:
            tok = entry["token"]
            entropy = shannon_entropy(tok)
            storage.upsert_token(
                token=tok,
                source=source_prefix,
                context=context,
                is_acronym=entry.get("is_acronym", False),
                is_camel=entry.get("is_camel", False),
                entropy=entropy,
                space_key=space_key,
                in_title=(context == "title"),
            )
            token_count += 1

    return token_count


def run(args: argparse.Namespace) -> None:
    global logger

    cfg = load_config(args.config)
    cfg = merge_cli_into_config(cfg, args)
    ensure_dirs(cfg)
    logger = setup_logging(cfg)

    logger.info("=" * 60)
    logger.info("confwordsmith starting")
    logger.info("=" * 60)

    start_time = time.time()

    confluence_cfg = cfg.get("confluence", {})
    if not confluence_cfg.get("url") or not confluence_cfg.get("token"):
        logger.error("Confluence URL and token are required")
        print("Error: --url and --token are required (or set in config.yaml)", file=sys.stderr)
        sys.exit(1)

    db_path = cfg.get("cache", {}).get("database", "./cache/confwordsmith.db")
    storage = Storage(db_path)

    try:
        client = ConfluenceClient(cfg, storage)

        # Phase 1: Discover spaces
        logger.info("Phase 1/6: Discovering spaces on %s", confluence_cfg["url"])
        spaces = client.list_spaces()
        if not spaces:
            logger.warning("No spaces found - check permissions and filters")
            print("Warning: No accessible spaces found.", file=sys.stderr)
            sys.exit(1)

        for sp in spaces:
            logger.info("  Space: %s (%s)", sp["key"], sp["name"])
        logger.info("Total spaces: %d", len(spaces))

        # Phase 2: Fetch pages
        logger.info("Phase 2/6: Fetching pages (incremental=%s, threads=%d)",
                     args.incremental, cfg.get("confluence", {}).get("threads", 4))
        pages = client.fetch_pages_incremental(spaces, incremental=args.incremental)
        logger.info("Retrieved %d pages total", len(pages))

        if not pages:
            logger.warning("No pages retrieved")
            print("No pages retrieved. Nothing to process.", file=sys.stderr)
            sys.exit(0)

        # Phase 3: Extract, tokenize, and scan for credentials
        logger.info("Phase 3/6: Extracting and tokenizing %d pages", len(pages))
        total_tokens = 0
        all_cred_finds: list[CredentialFind] = []
        for page_data in tqdm(pages, desc="Processing pages", unit="page"):
            page_content = extract_page(page_data)

            # Add space name as a token source
            for sp in spaces:
                if sp["key"] == page_content.space_key:
                    space_name = sp["name"]
                    space_tokens = tokenize_text(space_name, cfg)
                    stopwords = get_stopwords(cfg)
                    space_filtered = filter_tokens(space_tokens, cfg, stopwords)
                    for entry in space_filtered:
                        storage.upsert_token(
                            token=entry["token"],
                            source=f"{sp['key']}:space_name",
                            context="space_name",
                            is_acronym=entry.get("is_acronym", False),
                            is_camel=entry.get("is_camel", False),
                            entropy=shannon_entropy(entry["token"]),
                            space_key=sp["key"],
                        )
                    break

            stopwords = get_stopwords(cfg)
            count = process_page(page_content, cfg, storage, stopwords)
            total_tokens += count

            # Credential scanning
            if cfg.get("credential_scan", {}).get("enabled", True):
                cred_finds = scan_page_for_credentials(page_content)
                cred_finds.extend(scan_table_adjacency(page_content))
                for find in cred_finds:
                    storage.upsert_token(
                        token=find.value,
                        source=f"{find.space_key}:{find.page_id}",
                        context=f"credential:{find.pattern_name}",
                        entropy=shannon_entropy(find.value),
                        space_key=find.space_key,
                    )
                all_cred_finds.extend(cred_finds)

        logger.info("Total token insertions: %d", total_tokens)
        logger.info("Unique tokens in database: %d", storage.get_token_count())
        logger.info("Potential credentials found: %d", len(all_cred_finds))

        # Phase 4: Dictionary comparison
        dict_cfg = cfg.get("dictionary", {})
        dict_paths = dict_cfg.get("paths", [])
        dict_mode = dict_cfg.get("mode", "tag")
        if dict_paths:
            logger.info("Phase 4/6: Dictionary comparison (mode=%s, %d files)", dict_mode, len(dict_paths))
            all_tokens = storage.get_all_tokens()
            compared = compare_dictionary(all_tokens, dict_paths, dict_mode)

            compared_set = {t["token"] for t in compared}
            removed = [t["token"] for t in all_tokens if t["token"] not in compared_set]
            if removed:
                storage.delete_tokens(removed)
                logger.info("Deleted %d dictionary-matched tokens from database", len(removed))

            for t in compared:
                if t.get("dict_match"):
                    storage.mark_dict_match(t["token"])
        else:
            logger.info("Phase 4/6: Dictionary comparison skipped (no dictionaries configured)")

        # Phase 5: Score tokens
        logger.info("Phase 5/6: Scoring %d unique tokens", storage.get_token_count())
        score_all_tokens(storage, cfg)

        # Phase 6: Generate outputs
        logger.info("Phase 6/6: Generating output files to %s",
                     cfg.get("output", {}).get("directory", "./output"))
        output_paths = write_all_outputs(storage, cfg, credential_finds=all_cred_finds)

        elapsed = time.time() - start_time
        token_count = storage.get_token_count()

        logger.info("=" * 60)
        logger.info("confwordsmith complete in %.1fs", elapsed)
        logger.info("Unique tokens: %d", token_count)
        logger.info("Output files: %d", len(output_paths))
        logger.info("=" * 60)

        print(f"\nDone in {elapsed:.1f}s")
        print(f"  Spaces processed: {len(spaces)}")
        print(f"  Pages processed:  {len(pages)}")
        print(f"  Unique tokens:    {token_count}")
        print(f"  Output files:     {len(output_paths)}")
        for name, fpath in output_paths.items():
            print(f"    {name:25s} -> {fpath}")

    finally:
        storage.close()


def main() -> None:
    args = parse_args()
    try:
        run(args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"Fatal error: {exc}", file=sys.stderr)
        logging.getLogger("confwordsmith").exception("Unhandled exception")
        sys.exit(1)


if __name__ == "__main__":
    main()
