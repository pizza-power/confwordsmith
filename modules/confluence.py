"""Confluence REST API client with pagination, retries, rate limiting, and multithreading."""

from __future__ import annotations

import hashlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .storage import Storage

logger = logging.getLogger("confwordsmith.confluence")


class ConfluenceClient:
    """Handles communication with Confluence Cloud and Server/DC REST APIs."""

    CLOUD_API_PREFIX = "/wiki/api/v2"
    SERVER_REST_PREFIX = "/rest/api"

    def __init__(self, cfg: dict[str, Any], storage: Storage):
        cc = cfg.get("confluence", {})
        self.base_url: str = cc.get("url", "").rstrip("/")
        self.token: str = cc.get("token", "")
        self.auth_type: str = cc.get("auth_type", "bearer")
        self.username: str = cc.get("username", "")
        self.verify_ssl: bool = cc.get("verify_ssl", True)
        self.timeout: int = cc.get("timeout", 30)
        self.rate_delay: float = cc.get("rate_limit_delay", 0.5)
        self.max_pages: int = cc.get("max_pages", 0)
        self.threads: int = cc.get("threads", 4)
        self.storage = storage
        self.cfg = cfg

        self._is_cloud: Optional[bool] = None
        self.session = self._build_session(cc)

    def _build_session(self, cc: dict[str, Any]) -> requests.Session:
        session = requests.Session()

        retry = Retry(
            total=cc.get("max_retries", 3),
            backoff_factor=cc.get("retry_backoff", 2.0),
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        if self.auth_type == "basic" and self.username:
            session.auth = (self.username, self.token)
        else:
            session.headers["Authorization"] = f"Bearer {self.token}"

        session.headers["Accept"] = "application/json"
        session.verify = self.verify_ssl

        proxy = cc.get("proxy", "")
        if proxy:
            session.proxies = {"http": proxy, "https": proxy}

        return session

    @property
    def is_cloud(self) -> bool:
        if self._is_cloud is None:
            self._is_cloud = self._detect_cloud()
        return self._is_cloud

    def _detect_cloud(self) -> bool:
        """Probe the v2 Cloud API; fall back to Server if it 404s."""
        try:
            r = self.session.get(
                urljoin(self.base_url, f"{self.CLOUD_API_PREFIX}/spaces"),
                params={"limit": 1},
                timeout=self.timeout,
            )
            if r.status_code == 200:
                logger.info("Detected Confluence Cloud API")
                return True
        except requests.RequestException:
            pass
        logger.info("Using Confluence Server/Data Center API")
        return False

    # ── Low-Level Request ───────────────────────────────────────────────

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = urljoin(self.base_url, path)
        time.sleep(self.rate_delay)
        logger.debug("GET %s  params=%s", url, params)
        resp = self.session.get(url, params=params or {}, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    # ── Space Listing ───────────────────────────────────────────────────

    def list_spaces(self) -> list[dict[str, Any]]:
        spaces: list[dict[str, Any]] = []
        include = set(self.cfg.get("spaces", {}).get("include", []))
        exclude = set(self.cfg.get("spaces", {}).get("exclude", []))

        if self.is_cloud:
            cursor: Optional[str] = None
            while True:
                params: dict[str, Any] = {"limit": 50}
                if cursor:
                    params["cursor"] = cursor
                data = self._get(f"{self.CLOUD_API_PREFIX}/spaces", params)
                for sp in data.get("results", []):
                    key = sp.get("key", "")
                    if include and key not in include:
                        continue
                    if key in exclude:
                        continue
                    spaces.append({"key": key, "name": sp.get("name", key)})
                link = data.get("_links", {}).get("next")
                if not link:
                    break
                cursor = link.split("cursor=")[-1].split("&")[0] if "cursor=" in link else None
                if not cursor:
                    break
        else:
            start = 0
            while True:
                data = self._get(
                    f"{self.SERVER_REST_PREFIX}/space",
                    {"start": start, "limit": 50},
                )
                for sp in data.get("results", []):
                    key = sp.get("key", "")
                    if include and key not in include:
                        continue
                    if key in exclude:
                        continue
                    spaces.append({"key": key, "name": sp.get("name", key)})
                if data.get("size", 0) < 50:
                    break
                start += 50

        logger.info("Found %d spaces after filtering", len(spaces))
        return spaces

    # ── Page Listing ────────────────────────────────────────────────────

    def list_pages_in_space(self, space_key: str) -> list[dict[str, Any]]:
        """Return lightweight page stubs (id, title, version, updated) for a space."""
        pages: list[dict[str, Any]] = []
        collected = 0

        if self.is_cloud:
            cursor: Optional[str] = None
            while True:
                params: dict[str, Any] = {
                    "spaceId": self._get_cloud_space_id(space_key),
                    "limit": 50,
                    "sort": "-modified-date",
                }
                if cursor:
                    params["cursor"] = cursor
                data = self._get(f"{self.CLOUD_API_PREFIX}/pages", params)
                for p in data.get("results", []):
                    pages.append({
                        "id": str(p["id"]),
                        "title": p.get("title", ""),
                        "version": p.get("version", {}).get("number", 1)
                                   if isinstance(p.get("version"), dict)
                                   else 1,
                        "updated": p.get("version", {}).get("createdAt", "")
                                   if isinstance(p.get("version"), dict)
                                   else "",
                        "space_key": space_key,
                    })
                    collected += 1
                    if 0 < self.max_pages <= collected:
                        return pages
                link = data.get("_links", {}).get("next")
                if not link:
                    break
                cursor = link.split("cursor=")[-1].split("&")[0] if "cursor=" in link else None
                if not cursor:
                    break
        else:
            start = 0
            while True:
                data = self._get(
                    f"{self.SERVER_REST_PREFIX}/content",
                    {
                        "spaceKey": space_key,
                        "type": "page",
                        "start": start,
                        "limit": 50,
                        "orderby": "lastmodified desc",
                        "expand": "version",
                    },
                )
                for p in data.get("results", []):
                    ver = p.get("version", {})
                    pages.append({
                        "id": str(p["id"]),
                        "title": p.get("title", ""),
                        "version": ver.get("number", 1),
                        "updated": ver.get("when", ""),
                        "space_key": space_key,
                    })
                    collected += 1
                    if 0 < self.max_pages <= collected:
                        return pages
                if data.get("size", 0) < 50:
                    break
                start += 50

        return pages

    def _get_cloud_space_id(self, space_key: str) -> str:
        cache_key = f"cloud_space_id:{space_key}"
        cached = self.storage.get_sync_value(cache_key)
        if cached:
            return cached
        data = self._get(
            f"{self.CLOUD_API_PREFIX}/spaces",
            {"keys": space_key, "limit": 1},
        )
        results = data.get("results", [])
        if not results:
            raise ValueError(f"Space '{space_key}' not found in Cloud API")
        space_id = str(results[0]["id"])
        self.storage.set_sync_value(cache_key, space_id)
        return space_id

    # ── Full Page Fetch ─────────────────────────────────────────────────

    def fetch_page_content(self, page_id: str, space_key: str = "") -> dict[str, Any]:
        """Retrieve full page body, labels, and attachments."""
        if self.is_cloud:
            body_data = self._get(
                f"{self.CLOUD_API_PREFIX}/pages/{page_id}",
                {"body-format": "storage"},
            )
            body_html = (
                body_data.get("body", {}).get("storage", {}).get("value", "")
            )
            title = body_data.get("title", "")
            version = (
                body_data.get("version", {}).get("number", 1)
                if isinstance(body_data.get("version"), dict) else 1
            )
            author = (
                body_data.get("version", {}).get("by", {}).get("displayName", "")
                if isinstance(body_data.get("version"), dict) else ""
            )

            labels_data = self._get(f"{self.CLOUD_API_PREFIX}/pages/{page_id}/labels")
            labels = [l.get("name", "") for l in labels_data.get("results", [])]

            attachments: list[str] = []
            try:
                att_data = self._get(
                    f"{self.CLOUD_API_PREFIX}/pages/{page_id}/attachments"
                )
                attachments = [
                    a.get("title", "") for a in att_data.get("results", [])
                ]
            except requests.RequestException:
                logger.debug("Could not fetch attachments for page %s", page_id)

        else:
            data = self._get(
                f"{self.SERVER_REST_PREFIX}/content/{page_id}",
                {"expand": "body.storage,version,metadata.labels,children.attachment"},
            )
            body_html = data.get("body", {}).get("storage", {}).get("value", "")
            title = data.get("title", "")
            ver = data.get("version", {})
            version = ver.get("number", 1)
            author = ver.get("by", {}).get("displayName", "")
            labels = [
                l.get("name", "")
                for l in data.get("metadata", {}).get("labels", {}).get("results", [])
            ]
            attachments = [
                a.get("title", "")
                for a in data.get("children", {}).get("attachment", {}).get("results", [])
            ]

        body_hash = hashlib.sha256(body_html.encode("utf-8")).hexdigest()[:16]

        return {
            "page_id": page_id,
            "space_key": space_key,
            "title": title,
            "version": version,
            "author": author,
            "body_html": body_html,
            "labels": labels,
            "attachments": attachments,
            "body_hash": body_hash,
        }

    # ── Incremental / Threaded Retrieval ────────────────────────────────

    def fetch_pages_incremental(
        self,
        spaces: list[dict[str, Any]],
        incremental: bool = False,
    ) -> list[dict[str, Any]]:
        """Collect page stubs, filter by incremental cache, then fetch content in parallel."""
        all_stubs: list[dict[str, Any]] = []
        for sp in spaces:
            stubs = self.list_pages_in_space(sp["key"])
            all_stubs.extend(stubs)
            logger.info("Space %s: %d pages listed", sp["key"], len(stubs))

        if incremental:
            stubs_to_fetch = [
                s for s in all_stubs
                if self.storage.page_needs_update(s["id"], s.get("version", 0))
            ]
            logger.info(
                "Incremental: %d of %d pages need updating",
                len(stubs_to_fetch), len(all_stubs),
            )
        else:
            stubs_to_fetch = all_stubs

        results: list[dict[str, Any]] = []

        def _fetch_one(stub: dict[str, Any]) -> Optional[dict[str, Any]]:
            try:
                return self.fetch_page_content(stub["id"], stub.get("space_key", ""))
            except requests.RequestException as exc:
                logger.warning("Failed to fetch page %s: %s", stub["id"], exc)
                return None

        with ThreadPoolExecutor(max_workers=self.threads) as pool:
            futures = {pool.submit(_fetch_one, s): s for s in stubs_to_fetch}
            for fut in as_completed(futures):
                page_data = fut.result()
                if page_data:
                    results.append(page_data)
                    self.storage.upsert_page(
                        page_id=page_data["page_id"],
                        space_key=page_data["space_key"],
                        title=page_data["title"],
                        version=page_data["version"],
                        updated_at=page_data.get("updated", ""),
                        body_hash=page_data.get("body_hash", ""),
                        labels=page_data.get("labels", []),
                        author=page_data.get("author", ""),
                    )

        logger.info("Fetched %d pages successfully", len(results))
        return results
