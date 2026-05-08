"""SQLite storage layer for page cache, token metadata, scoring, and sync tracking."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class Storage:
    """Thread-safe SQLite wrapper for confwordsmith data."""

    def __init__(self, db_path: str = "./cache/confwordsmith.db"):
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = str(path)
        self._local = threading.local()
        self._init_schema(self._get_conn())

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return self._local.conn

    @staticmethod
    def _init_schema(conn: sqlite3.Connection) -> None:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS pages (
                page_id     TEXT PRIMARY KEY,
                space_key   TEXT NOT NULL,
                title       TEXT NOT NULL,
                version     INTEGER NOT NULL DEFAULT 0,
                updated_at  TEXT NOT NULL,
                fetched_at  TEXT NOT NULL,
                body_hash   TEXT,
                labels      TEXT DEFAULT '[]',
                author      TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS tokens (
                token       TEXT PRIMARY KEY,
                frequency   INTEGER NOT NULL DEFAULT 1,
                score       REAL NOT NULL DEFAULT 0.0,
                sources     TEXT NOT NULL DEFAULT '[]',
                contexts    TEXT NOT NULL DEFAULT '[]',
                first_seen  TEXT NOT NULL,
                last_seen   TEXT NOT NULL,
                is_acronym  INTEGER NOT NULL DEFAULT 0,
                is_camel    INTEGER NOT NULL DEFAULT 0,
                entropy     REAL NOT NULL DEFAULT 0.0,
                space_count INTEGER NOT NULL DEFAULT 1,
                in_title    INTEGER NOT NULL DEFAULT 0,
                dict_match  INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS sync_state (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_pages_space ON pages(space_key);
            CREATE INDEX IF NOT EXISTS idx_pages_updated ON pages(updated_at);
            CREATE INDEX IF NOT EXISTS idx_tokens_score ON tokens(score DESC);
            CREATE INDEX IF NOT EXISTS idx_tokens_freq ON tokens(frequency DESC);
        """)
        conn.commit()

    # ── Page Cache ──────────────────────────────────────────────────────

    def get_page(self, page_id: str) -> Optional[dict[str, Any]]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM pages WHERE page_id = ?", (page_id,)
        ).fetchone()
        return dict(row) if row else None

    def upsert_page(
        self,
        page_id: str,
        space_key: str,
        title: str,
        version: int,
        updated_at: str,
        body_hash: str = "",
        labels: list[str] | None = None,
        author: str = "",
    ) -> None:
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO pages (page_id, space_key, title, version, updated_at,
                                  fetched_at, body_hash, labels, author)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(page_id) DO UPDATE SET
                   space_key  = excluded.space_key,
                   title      = excluded.title,
                   version    = excluded.version,
                   updated_at = excluded.updated_at,
                   fetched_at = excluded.fetched_at,
                   body_hash  = excluded.body_hash,
                   labels     = excluded.labels,
                   author     = excluded.author
            """,
            (
                page_id, space_key, title, version, updated_at,
                now, body_hash, json.dumps(labels or []), author,
            ),
        )
        conn.commit()

    def page_needs_update(self, page_id: str, remote_version: int) -> bool:
        cached = self.get_page(page_id)
        if cached is None:
            return True
        return cached["version"] < remote_version

    def get_all_page_ids(self) -> set[str]:
        conn = self._get_conn()
        rows = conn.execute("SELECT page_id FROM pages").fetchall()
        return {r["page_id"] for r in rows}

    # ── Token Metadata ──────────────────────────────────────────────────

    def upsert_token(
        self,
        token: str,
        source: str = "",
        context: str = "",
        is_acronym: bool = False,
        is_camel: bool = False,
        entropy: float = 0.0,
        space_key: str = "",
        in_title: bool = False,
    ) -> None:
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        existing = conn.execute(
            "SELECT * FROM tokens WHERE token = ?", (token,)
        ).fetchone()

        if existing:
            sources = json.loads(existing["sources"])
            contexts = json.loads(existing["contexts"])
            if source and source not in sources:
                sources.append(source)
            if context and context not in contexts:
                contexts.append(context)

            spaces_set = set()
            for s in sources:
                parts = s.split(":", 1)
                if parts:
                    spaces_set.add(parts[0])

            conn.execute(
                """UPDATE tokens SET
                       frequency   = frequency + 1,
                       sources     = ?,
                       contexts    = ?,
                       last_seen   = ?,
                       is_acronym  = MAX(is_acronym, ?),
                       is_camel    = MAX(is_camel, ?),
                       entropy     = ?,
                       space_count = ?,
                       in_title    = MAX(in_title, ?)
                   WHERE token = ?""",
                (
                    json.dumps(sources), json.dumps(contexts), now,
                    int(is_acronym), int(is_camel), entropy,
                    len(spaces_set), int(in_title), token,
                ),
            )
        else:
            sources = [source] if source else []
            contexts = [context] if context else []
            conn.execute(
                """INSERT INTO tokens
                       (token, frequency, score, sources, contexts,
                        first_seen, last_seen, is_acronym, is_camel,
                        entropy, space_count, in_title)
                   VALUES (?, 1, 0.0, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                (
                    token, json.dumps(sources), json.dumps(contexts),
                    now, now, int(is_acronym), int(is_camel), entropy,
                    int(in_title),
                ),
            )
        conn.commit()

    def update_token_score(self, token: str, score: float) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE tokens SET score = ? WHERE token = ?", (score, token)
        )
        conn.commit()

    def mark_dict_match(self, token: str) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE tokens SET dict_match = 1 WHERE token = ?", (token,)
        )
        conn.commit()

    def get_all_tokens(self) -> list[dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM tokens ORDER BY score DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_tokens_above_score(self, threshold: float) -> list[dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM tokens WHERE score >= ? ORDER BY score DESC",
            (threshold,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_token_count(self) -> int:
        conn = self._get_conn()
        row = conn.execute("SELECT COUNT(*) AS cnt FROM tokens").fetchone()
        return row["cnt"] if row else 0

    # ── Sync State ──────────────────────────────────────────────────────

    def get_sync_value(self, key: str) -> Optional[str]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT value FROM sync_state WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set_sync_value(self, key: str, value: str) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO sync_state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
