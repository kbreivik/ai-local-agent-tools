"""Bookstack → doc_chunks RAG sync.

Fetches all Bookstack pages via the REST API, strips HTML to plain text,
chunks each page, and upserts into doc_chunks via api/rag/ingest.py.
Supports incremental sync: only fetches pages updated after last_sync_at.

Connection resolution order:
  1. Connections DB (platform="bookstack") — token_id / token_secret in credentials
  2. Env vars: BOOKSTACK_HOST, BOOKSTACK_TOKEN_ID, BOOKSTACK_TOKEN_SECRET

Sync state is stored in status_snapshots (component="bookstack_sync").
"""
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from html.parser import HTMLParser

log = logging.getLogger(__name__)

# ── Background scheduler ─────────────────────────────────────────────────────

_sync_timer: "threading.Timer | None" = None
_sync_lock = threading.Lock()
_last_sync_result: dict = {}


def start_bookstack_scheduler() -> None:
    """Start the background sync timer. Called from lifespan on startup."""
    _schedule_next()
    log.info("Bookstack sync scheduler started")


def stop_bookstack_scheduler() -> None:
    """Cancel the background sync timer. Called from lifespan on shutdown."""
    global _sync_timer
    if _sync_timer is not None:
        _sync_timer.cancel()
        _sync_timer = None


def _schedule_next() -> None:
    global _sync_timer
    if _sync_timer is not None:
        _sync_timer.cancel()
    interval_hours = _get_interval_hours()
    if not _is_sync_enabled():
        log.debug("Bookstack sync disabled — not scheduling")
        return
    delay = interval_hours * 3600
    _sync_timer = threading.Timer(delay, _run_scheduled_sync)
    _sync_timer.daemon = True
    _sync_timer.start()
    log.debug("Bookstack sync scheduled in %.1fh", interval_hours)


def _run_scheduled_sync() -> None:
    run_sync(incremental=True)
    _schedule_next()


def _is_sync_enabled() -> bool:
    try:
        from mcp_server.tools.skills.storage import get_backend
        val = get_backend().get_setting("bookstackSyncEnabled")
        if val is None:
            return False
        return str(val).lower() in ("true", "1", "yes")
    except Exception:
        return False


def _get_interval_hours() -> float:
    try:
        from mcp_server.tools.skills.storage import get_backend
        val = get_backend().get_setting("bookstackSyncIntervalHours")
        return max(0.5, float(val)) if val is not None else 6.0
    except Exception:
        return 6.0


# ── Connection resolution ────────────────────────────────────────────────────

def _resolve_connection() -> dict | None:
    """Return {"host": str, "token_id": str, "token_secret": str} or None."""
    # Try connections DB first
    try:
        from api.connections import get_connection_for_platform
        conn = get_connection_for_platform("bookstack")
        if conn:
            creds = conn.get("credentials") or {}
            if isinstance(creds, str):
                try:
                    creds = json.loads(creds)
                except Exception:
                    creds = {}
            host = conn.get("host", "")
            token_id = creds.get("token_id", "") or creds.get("api_key", "")
            token_secret = creds.get("token_secret", "") or creds.get("secret", "")
            if host and token_id and token_secret:
                return {"host": host.rstrip("/"), "token_id": token_id, "token_secret": token_secret}
    except Exception:
        pass
    # Fall back to env vars
    host = os.environ.get("BOOKSTACK_HOST", "").rstrip("/")
    token_id = os.environ.get("BOOKSTACK_TOKEN_ID", "")
    token_secret = os.environ.get("BOOKSTACK_TOKEN_SECRET", "")
    if host and token_id and token_secret:
        return {"host": host, "token_id": token_id, "token_secret": token_secret}
    return None


# ── HTML stripping ───────────────────────────────────────────────────────────

class _HTMLStripper(HTMLParser):
    """Minimal stdlib HTML-to-text converter. Preserves newlines at block boundaries."""
    _BLOCK = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "br",
               "tr", "td", "th", "blockquote", "pre", "code"}

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip = True
        if tag in self._BLOCK:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = False
        if tag in self._BLOCK:
            self._parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self._parts.append(data)

    def get_text(self) -> str:
        import re
        text = "".join(self._parts)
        # Collapse excessive blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def _html_to_text(html: str) -> str:
    stripper = _HTMLStripper()
    try:
        stripper.feed(html)
        return stripper.get_text()
    except Exception:
        # Crude fallback
        import re
        return re.sub(r"<[^>]+>", " ", html).strip()


# ── Sync state via status_snapshots ─────────────────────────────────────────

def _load_sync_state() -> dict:
    """Load last sync state from status_snapshots."""
    try:
        import psycopg2
        dsn = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
        if not dsn:
            return {}
        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            "SELECT state FROM status_snapshots WHERE component = 'bookstack_sync' ORDER BY timestamp DESC LIMIT 1"
        )
        row = cur.fetchone()
        cur.close(); conn.close()
        if row:
            state = row[0]
            if isinstance(state, str):
                state = json.loads(state)
            return state or {}
    except Exception:
        pass
    return {}


def _save_sync_state(state: dict) -> None:
    """Persist sync state to status_snapshots."""
    try:
        import psycopg2
        dsn = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
        if not dsn:
            return
        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO status_snapshots (component, state, timestamp)
            VALUES ('bookstack_sync', %s, NOW())
        """, (json.dumps(state),))
        cur.close(); conn.close()
    except Exception as e:
        log.warning("Bookstack sync: failed to save state: %s", e)


# ── Bookstack API client ─────────────────────────────────────────────────────

def _api_get(base_url: str, path: str, headers: dict, params: dict = None) -> dict:
    import httpx
    r = httpx.get(f"{base_url}{path}", headers=headers, params=params,
                  verify=False, timeout=30)
    r.raise_for_status()
    return r.json()


def _fetch_all_pages(base_url: str, headers: dict, since_iso: str | None = None) -> list[dict]:
    """Fetch page stubs (id, name, book_id, updated_at) with pagination."""
    pages = []
    offset = 0
    count = 100
    while True:
        params = {"count": count, "offset": offset, "sort": "+updated_at"}
        data = _api_get(base_url, "/api/pages", headers, params)
        batch = data.get("data", [])
        if not batch:
            break
        for p in batch:
            # Incremental: skip pages not updated since last sync
            if since_iso and p.get("updated_at", "") <= since_iso:
                continue
            pages.append(p)
        total = data.get("total", 0)
        offset += count
        if offset >= total:
            break
    return pages


def _fetch_page_content(base_url: str, headers: dict, page_id: int) -> dict:
    """Fetch full page content. Returns dict with html, markdown, name, book_id."""
    return _api_get(base_url, f"/api/pages/{page_id}", headers)


def _fetch_book_name(base_url: str, headers: dict, book_id: int, _cache: dict = {}) -> str:
    if book_id in _cache:
        return _cache[book_id]
    try:
        data = _api_get(base_url, f"/api/books/{book_id}", headers)
        name = data.get("name", f"Book {book_id}")
    except Exception:
        name = f"Book {book_id}"
    _cache[book_id] = name
    return name


# ── Main sync entry point ────────────────────────────────────────────────────

def run_sync(incremental: bool = True) -> dict:
    """Run a full or incremental Bookstack → doc_chunks sync.

    Returns {"status": "ok"|"error", "pages_synced": int, "chunks_upserted": int, ...}
    """
    global _last_sync_result

    if not _sync_lock.acquire(blocking=False):
        return {"status": "error", "message": "Sync already in progress"}

    try:
        c = _resolve_connection()
        if not c:
            result = {"status": "error", "message": "No Bookstack connection configured. "
                      "Add a 'bookstack' connection in Settings → Connections or set "
                      "BOOKSTACK_HOST / BOOKSTACK_TOKEN_ID / BOOKSTACK_TOKEN_SECRET env vars."}
            _last_sync_result = result
            return result

        base_url = f"https://{c['host']}"
        headers = {
            "Authorization": f"Token {c['token_id']}:{c['token_secret']}",
            "Content-Type": "application/json",
        }

        state = _load_sync_state()
        since_iso = state.get("last_sync_at") if incremental else None

        log.info("Bookstack sync started (incremental=%s, since=%s)", incremental, since_iso)

        from api.rag.chunker import chunk_document
        from api.rag.ingest import ingest_chunks

        pages = _fetch_all_pages(base_url, headers, since_iso)
        log.info("Bookstack: %d page(s) to sync", len(pages))

        pages_synced = 0
        chunks_upserted = 0
        errors = []

        for stub in pages:
            page_id = stub.get("id")
            page_name = stub.get("name", f"Page {page_id}")
            book_id = stub.get("book_id", 0)
            try:
                full = _fetch_page_content(base_url, headers, page_id)
                html = full.get("html", "") or ""
                markdown = full.get("markdown", "") or ""
                # Prefer markdown (cleaner text), fall back to HTML
                text = markdown.strip() if markdown.strip() else _html_to_text(html)
                if not text:
                    continue

                book_name = _fetch_book_name(base_url, headers, book_id)
                source_label = f"{book_name} / {page_name}"
                source_url = f"{base_url}/books/{book_id}/page/{page_id}"
                page_updated = full.get("updated_at", "")
                version = page_updated[:10] if page_updated else ""

                chunks = chunk_document(text, "admin_guide")
                n = ingest_chunks(
                    chunks=chunks,
                    platform="bookstack",
                    doc_type="admin_guide",
                    source_url=source_url,
                    source_label=source_label,
                    version=version,
                )
                chunks_upserted += n
                pages_synced += 1
            except Exception as e:
                log.warning("Bookstack: failed to sync page %s: %s", page_id, e)
                errors.append(str(e)[:80])

        now_iso = datetime.now(timezone.utc).isoformat()
        new_state = {
            "last_sync_at": now_iso,
            "last_sync_pages": pages_synced,
            "last_sync_chunks": chunks_upserted,
            "last_sync_errors": len(errors),
            "incremental": incremental,
        }
        _save_sync_state(new_state)

        result = {
            "status": "ok",
            "pages_synced": pages_synced,
            "chunks_upserted": chunks_upserted,
            "errors": len(errors),
            "error_samples": errors[:3],
            "incremental": incremental,
            "synced_at": now_iso,
        }
        _last_sync_result = result
        log.info("Bookstack sync done: %d pages, %d chunks, %d errors",
                 pages_synced, chunks_upserted, len(errors))
        return result

    except Exception as e:
        log.error("Bookstack sync failed: %s", e)
        result = {"status": "error", "message": str(e)}
        _last_sync_result = result
        return result
    finally:
        _sync_lock.release()


def get_sync_status() -> dict:
    """Return last sync result merged with current scheduler state."""
    state = _load_sync_state()
    return {
        **_last_sync_result,
        "sync_enabled": _is_sync_enabled(),
        "sync_interval_hours": _get_interval_hours(),
        "last_sync_at": state.get("last_sync_at"),
        "last_sync_pages": state.get("last_sync_pages", 0),
        "last_sync_chunks": state.get("last_sync_chunks", 0),
        "last_sync_errors": state.get("last_sync_errors", 0),
        "scheduler_running": _sync_timer is not None and _sync_timer.is_alive(),
    }
