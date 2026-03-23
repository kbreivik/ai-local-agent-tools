"""
Documentation fetcher — downloads official docs and ingests into MuninnDB.

Run as CLI:
    python -m api.memory.fetch_docs                  # all sources
    python -m api.memory.fetch_docs --component kafka # single source

Each page is converted from HTML → markdown (via html2text),
split into ≤400-word chunks, and stored as MuninnDB engrams.

Deduplication: if engrams for a source exist and were fetched within
REFRESH_DAYS days, they are skipped. Older engrams are deleted first.
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

from api.constants import APP_NAME, APP_VERSION

# ── Source definitions ─────────────────────────────────────────────────────────

SOURCES: list[dict] = [
    {
        "name":      "kafka-docs",
        "component": "kafka",
        "url":       "https://kafka.apache.org/documentation/",
        "tags":      ["documentation", "kafka-docs", "kafka"],
    },
    {
        "name":      "nginx-docs",
        "component": "nginx",
        "url":       "https://nginx.org/en/docs/",
        "tags":      ["documentation", "nginx-docs", "nginx"],
    },
    {
        "name":      "elastic-docs",
        "component": "elasticsearch",
        "url":       "https://www.elastic.co/guide/en/elasticsearch/reference/current/index.html",
        "tags":      ["documentation", "elastic-docs", "elasticsearch"],
    },
    {
        "name":      "swarm-docs",
        "component": "swarm",
        "url":       "https://docs.docker.com/engine/swarm/",
        "tags":      ["documentation", "swarm-docs", "docker", "swarm"],
    },
    {
        "name":      "filebeat-docs",
        "component": "filebeat",
        "url":       "https://www.elastic.co/guide/en/beats/filebeat/current/index.html",
        "tags":      ["documentation", "filebeat-docs", "filebeat"],
    },
]

SOURCE_BY_COMPONENT = {s["component"]: s for s in SOURCES}

REFRESH_DAYS  = 30
MAX_WORDS     = 400
MAX_BYTES     = 600_000   # cap response size to avoid huge pages
FETCH_TIMEOUT = 20        # seconds

# Local manifest — tracks ingestion timestamps without relying on MuninnDB search
import pathlib as _pathlib
MANIFEST_PATH = _pathlib.Path(__file__).parent.parent.parent / "data" / "docs_manifest.json"


# ── HTML → Markdown conversion ─────────────────────────────────────────────────

def _html_to_markdown(html: str) -> str:
    try:
        import html2text
        h = html2text.HTML2Text()
        h.ignore_links      = True
        h.ignore_images     = True
        h.ignore_tables     = False
        h.body_width        = 0        # no line wrapping
        h.skip_internal_links = True
        return h.handle(html)
    except ImportError:
        # Fallback: strip all tags with regex
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>',  '', text,  flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'&nbsp;', ' ', text)
        text = re.sub(r'&lt;',   '<', text)
        text = re.sub(r'&gt;',   '>', text)
        text = re.sub(r'&amp;',  '&', text)
        text = re.sub(r' {2,}',  ' ', text)
        return text


# ── Chunking ───────────────────────────────────────────────────────────────────

def chunk_markdown(text: str, max_words: int = MAX_WORDS) -> list[tuple[str, str]]:
    """
    Split markdown into (heading, chunk_text) pairs.

    Strategy:
      1. Split on ## / ### headings — keep heading with its section.
      2. If a section > max_words, split on double-newlines (paragraphs).
      3. If a paragraph > max_words, split on sentence boundaries.
    """
    # Split on heading lines (# / ## / ###)
    sections = re.split(r'\n(?=#{1,3} )', text.strip())
    chunks: list[tuple[str, str]] = []

    for section in sections:
        if not section.strip():
            continue
        lines   = section.strip().splitlines()
        heading = lines[0].lstrip('#').strip() if lines and lines[0].startswith('#') else 'Overview'
        words   = section.split()

        if len(words) <= max_words:
            if len(words) >= 10:          # skip tiny noise sections
                chunks.append((heading, section.strip()))
        else:
            # Split on paragraphs
            paras = re.split(r'\n\n+', section)
            buf:  list[str] = []
            wbuf: int       = 0

            for para in paras:
                pw = len(para.split())
                if pw == 0:
                    continue

                if pw > max_words:
                    # Split on sentence boundaries
                    sentences = re.split(r'(?<=[.!?])\s+', para)
                    for sent in sentences:
                        sw = len(sent.split())
                        if wbuf + sw > max_words and buf:
                            chunks.append((heading, '\n\n'.join(buf)))
                            buf, wbuf = [], 0
                        buf.append(sent)
                        wbuf += sw
                else:
                    if wbuf + pw > max_words and buf:
                        chunks.append((heading, '\n\n'.join(buf)))
                        buf, wbuf = [], 0
                    buf.append(para)
                    wbuf += pw

            if buf:
                body = '\n\n'.join(buf)
                if len(body.split()) >= 10:
                    chunks.append((heading, body))

    return chunks


# ── Fetch ──────────────────────────────────────────────────────────────────────

def _fetch_url(url: str) -> Optional[str]:
    """Fetch URL, return HTML string or None on error."""
    try:
        import requests
        headers = {"User-Agent": f"{APP_NAME}/{APP_VERSION} (doc-ingestion)"}
        r = requests.get(url, headers=headers, timeout=FETCH_TIMEOUT, stream=True)
        r.raise_for_status()

        # Read up to MAX_BYTES to avoid enormous pages
        content = b""
        for chunk in r.iter_content(chunk_size=8192):
            content += chunk
            if len(content) >= MAX_BYTES:
                break
        return content.decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[docs] ERROR fetching {url}: {e}", file=sys.stderr)
        return None


# ── Deduplication helpers ──────────────────────────────────────────────────────

def _concept(source_name: str, idx: int) -> str:
    return f"docs:{source_name}:{idx:04d}"


def _parse_fetched_at(content: str) -> Optional[datetime]:
    """Extract fetched_at timestamp embedded in engram content."""
    m = re.search(r'fetched_at:\s*(\S+)', content)
    if not m:
        return None
    try:
        return datetime.fromisoformat(m.group(1).rstrip(']'))
    except ValueError:
        return None


# ── Local manifest (dedup) ────────────────────────────────────────────────────

def _read_manifest() -> dict:
    """Read docs_manifest.json, return {} on missing/corrupt."""
    try:
        if MANIFEST_PATH.exists():
            import json as _json
            return _json.loads(MANIFEST_PATH.read_text())
    except Exception:
        pass
    return {}


def _write_manifest(data: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    import json as _json
    MANIFEST_PATH.write_text(_json.dumps(data, indent=2))


def _manifest_check(source_name: str) -> tuple[int, Optional[datetime]]:
    """Return (chunks, last_fetched) from local manifest, or (0, None)."""
    m = _read_manifest().get(source_name, {})
    if not m:
        return 0, None
    try:
        ts = datetime.fromisoformat(m["ingested"])
        return int(m.get("chunks", 0)), ts
    except Exception:
        return 0, None


def _manifest_ids(source_name: str) -> list[str]:
    """Return stored engram IDs for a source, or empty list."""
    return _read_manifest().get(source_name, {}).get("ids", [])


def _manifest_update(source_name: str, chunks: int, ts: str, ids: list[str]) -> None:
    data = _read_manifest()
    data[source_name] = {"ingested": ts, "chunks": chunks, "ids": ids}
    _write_manifest(data)


def _manifest_clear(source_name: str) -> None:
    data = _read_manifest()
    data.pop(source_name, None)
    _write_manifest(data)


async def _delete_existing(client, source_name: str) -> int:
    """
    Delete all chunk engrams for a source from MuninnDB.
    Uses stored IDs from the manifest for exact targeting.
    """
    deleted = 0
    ids = _manifest_ids(source_name)
    for eid in ids:
        if await client.delete(eid):
            deleted += 1
    _manifest_clear(source_name)
    return deleted


# ── Ingestion ──────────────────────────────────────────────────────────────────

async def ingest_source(
    source: dict,
    force: bool = False,
    client=None,
) -> dict:
    """
    Fetch, chunk, and ingest a single documentation source.

    Returns:
        {"component": ..., "status": "ok"|"skipped"|"error",
         "chunks": N, "message": "..."}
    """
    if client is None:
        from api.memory.client import get_client
        client = get_client()

    name      = source["name"]
    component = source["component"]
    url       = source["url"]
    tags      = source["tags"]

    print(f"[docs] Checking {name}…")

    count, last_fetched = _manifest_check(name)

    if count > 0:
        if not force:
            age = (
                datetime.now(timezone.utc) - last_fetched.replace(tzinfo=timezone.utc)
                if last_fetched else timedelta(days=999)
            )
            if age.days < REFRESH_DAYS:
                msg = f"skipped ({count} chunks, fetched {age.days}d ago)"
                print(f"[docs] {name}: {msg}")
                return {"component": component, "source": name,
                        "status": "skipped", "chunks": count, "message": msg}

        # Stale or forced — delete existing chunks before re-fetch
        deleted = await _delete_existing(client, name)
        print(f"[docs] {name}: deleted {deleted} old chunks, re-fetching…")

    print(f"[docs] Fetching {url}…")
    html = await asyncio.get_event_loop().run_in_executor(None, _fetch_url, url)
    if html is None:
        return {"component": component, "source": name,
                "status": "error", "chunks": 0,
                "message": f"Failed to fetch {url}"}

    markdown = _html_to_markdown(html)
    chunks   = chunk_markdown(markdown, MAX_WORDS)

    if not chunks:
        return {"component": component, "source": name,
                "status": "error", "chunks": 0,
                "message": "No usable content after chunking"}

    ts = datetime.now(timezone.utc).isoformat()
    ingested = 0
    stored_ids: list[str] = []

    for i, (heading, text) in enumerate(chunks):
        concept = _concept(name, i)
        content = (
            f"[source: {name} | component: {component} | "
            f"chunk: {i:04d} | fetched_at: {ts}]\n\n"
            f"## {heading}\n\n{text}"
        )
        eid = await client.store(concept, content, tags)
        if eid:
            ingested += 1
            stored_ids.append(eid)

        # Brief pause every 20 stores to avoid overwhelming MuninnDB
        if i % 20 == 19:
            await asyncio.sleep(0.1)

    # Update local manifest — store IDs for exact deletion on re-fetch
    _manifest_update(name, ingested, ts, stored_ids)

    msg = f"{ingested}/{len(chunks)} chunks ingested"
    print(f"[docs] {name}: {msg}")
    return {"component": component, "source": name,
            "status": "ok", "chunks": ingested, "message": msg}


async def ingest_all(components: list[str] | None = None, force: bool = False) -> list[dict]:
    """Ingest all sources (or a subset by component name)."""
    from api.memory.client import get_client
    client = get_client()

    sources = SOURCES
    if components:
        sources = [s for s in SOURCES if s["component"] in components]
        unknown = set(components) - {s["component"] for s in SOURCES}
        if unknown:
            print(f"[docs] Unknown components: {unknown}", file=sys.stderr)

    results = []
    total   = 0
    for source in sources:
        r = await ingest_source(source, force=force, client=client)
        results.append(r)
        if r["status"] == "ok":
            total += r["chunks"]

    if total > 0:
        print(f"[docs] Total: {total} new chunks ingested into MuninnDB")
    return results


async def get_docs_status() -> list[dict]:
    """Return status of each documentation source from local manifest."""
    result = []
    for source in SOURCES:
        count, last_fetched = _manifest_check(source["name"])
        fresh = False
        if last_fetched:
            age = datetime.now(timezone.utc) - last_fetched.replace(tzinfo=timezone.utc)
            fresh = age.days < REFRESH_DAYS
        result.append({
            "component":    source["component"],
            "source":       source["name"],
            "url":          source["url"],
            "chunks":       count,
            "last_fetched": last_fetched.isoformat() if last_fetched else None,
            "fresh":        fresh,
        })
    return result


# ── CLI entry point ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Ingest documentation into MuninnDB")
    parser.add_argument(
        "--component", "-c",
        nargs="*",
        metavar="COMPONENT",
        help=f"Components to fetch ({', '.join(s['component'] for s in SOURCES)}). "
             "Omit for all.",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Re-fetch even if docs are fresh (< 30 days old)",
    )
    args = parser.parse_args()

    results = asyncio.run(ingest_all(
        components=args.component or None,
        force=args.force,
    ))

    ok      = sum(1 for r in results if r["status"] == "ok")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    errors  = sum(1 for r in results if r["status"] == "error")
    print(f"\n[docs] Done — ok:{ok}  skipped:{skipped}  errors:{errors}")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
