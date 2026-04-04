"""
URL/PDF ingestion pipeline.

Workflow:
  1. fetch_url(url) or parse_pdf(path) → raw text
  2. chunk_text(text) → list of chunks
  3. check_if_updated(url/filename) → diff against stored version
  4. chunk_and_store(chunks, source, tags) → MuninnDB engram IDs
  5. detect_breaking_changes(old, new) → LLM analysis + raw diff

Local storage: data/docs/
Manifest: data/docs/manifest.json — {source_key: {stored_at, muninndb_ids, content_hash, local_path}}
"""
import hashlib
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

DOCS_DIR = Path(__file__).parent.parent.parent / "data" / "docs"
MANIFEST_PATH = DOCS_DIR / "manifest.json"

# Max chars per MuninnDB engram chunk
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 100


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_docs_dir():
    DOCS_DIR.mkdir(parents=True, exist_ok=True)


def _load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        try:
            return json.loads(MANIFEST_PATH.read_text())
        except Exception:
            return {}
    return {}


def _save_manifest(manifest: dict):
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _url_key(url: str) -> str:
    """Stable manifest key from URL."""
    return re.sub(r'[^\w.-]', '_', url)[:80]


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks."""
    if not text or len(text) <= chunk_size:
        return [text] if text else []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks


async def fetch_url(url: str) -> tuple[str, str]:
    """
    Fetch URL and extract readable text.
    Returns (raw_html, clean_text).
    """
    import httpx

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; HP1-Agent/1.0; research-bot)",
        "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain",
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        content_type = r.headers.get("content-type", "")
        raw = r.text

    # Extract clean text
    clean = _extract_text_from_html(raw)
    return raw, clean


def _extract_text_from_html(html: str) -> str:
    """Extract readable text from HTML — strips tags, scripts, styles."""
    # Try trafilatura first (best quality)
    try:
        import trafilatura
        result = trafilatura.extract(html, include_comments=False, include_tables=True)
        if result and len(result) > 100:
            return result
    except ImportError:
        pass

    # Fallback: basic tag stripping
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'&\w+;', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def parse_pdf(file_path: str) -> str:
    """Extract text from a PDF file."""
    # Try pypdf first
    try:
        import pypdf
        reader = pypdf.PdfReader(file_path)
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        return "\n\n".join(pages)
    except ImportError:
        pass

    # Try pdfminer
    try:
        from pdfminer.high_level import extract_text
        return extract_text(file_path)
    except ImportError:
        pass

    raise RuntimeError(
        "No PDF parser available. Install with: pip install pypdf  OR  pip install pdfminer.six"
    )


def _diff_text(old: str, new: str) -> str:
    """Generate a unified diff summary between old and new content."""
    import difflib
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = list(difflib.unified_diff(
        old_lines[:200], new_lines[:200],
        fromfile="stored", tofile="new",
        n=2,
    ))
    if not diff:
        return ""
    # Return first 3000 chars of diff
    return "".join(diff)[:3000]


def check_if_updated(source_key: str, new_content: str) -> dict:
    """
    Compare new content against stored version.
    Returns {is_new, is_updated, old_hash, new_hash, diff_snippet}.
    """
    manifest = _load_manifest()
    entry = manifest.get(source_key)
    new_hash = _content_hash(new_content)

    if not entry:
        return {"is_new": True, "is_updated": False, "old_hash": None, "new_hash": new_hash, "diff_snippet": None}

    old_hash = entry.get("content_hash", "")
    if old_hash == new_hash:
        return {"is_new": False, "is_updated": False, "old_hash": old_hash, "new_hash": new_hash, "diff_snippet": None}

    # Load old content from local file for diff
    local_path = entry.get("local_path", "")
    diff_snippet = None
    if local_path and Path(local_path).exists():
        old_content = Path(local_path).read_text(encoding="utf-8", errors="replace")
        diff_snippet = _diff_text(old_content, new_content)

    return {
        "is_new": False,
        "is_updated": True,
        "old_hash": old_hash,
        "new_hash": new_hash,
        "diff_snippet": diff_snippet,
    }


async def detect_breaking_changes_llm(diff_snippet: str, source: str) -> str:
    """
    Use the local LLM to analyze a diff and identify breaking changes.
    Returns a concise analysis string.
    """
    import os
    try:
        from openai import OpenAI
        from api.constants import DEFAULT_LM_STUDIO_URL, DEFAULT_LM_STUDIO_KEY
        client = OpenAI(
            base_url=os.environ.get("LM_STUDIO_BASE_URL", DEFAULT_LM_STUDIO_URL),
            api_key=os.environ.get("LM_STUDIO_API_KEY", DEFAULT_LM_STUDIO_KEY),
        )
        prompt = f"""Analyze this documentation diff for {source} and identify:
1. Breaking API changes (removed/renamed endpoints, changed parameters, incompatible behavior)
2. Deprecations
3. New required configuration

Keep your response under 200 words. If no breaking changes, say "No breaking changes detected."

DIFF:
{diff_snippet[:2000]}"""

        response = client.chat.completions.create(
            model=os.environ.get("LM_STUDIO_MODEL", "lmstudio-community/qwen3-coder-30b-a3b-instruct"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=300,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"LLM analysis unavailable: {e}"


def _save_local(source_key: str, content: str, suffix: str = ".txt") -> str:
    """Save content to data/docs/ and return the path."""
    _ensure_docs_dir()
    filename = f"{source_key}{suffix}"
    path = DOCS_DIR / filename
    path.write_text(content, encoding="utf-8")
    return str(path)


async def chunk_and_store(
    content: str,
    source: str,
    tags: list[str],
    source_key: str,
    local_path: str,
    platform: str = "",
    doc_type: str = "admin_guide",
) -> list[str]:
    """
    Chunk content and store each chunk as a MuninnDB engram.
    Also writes to pgvector doc_chunks table (parallel store).
    Returns list of engram IDs (or empty list if MuninnDB unavailable).
    """
    from api.memory.client import get_client
    client = get_client()

    chunks = chunk_text(content)
    engram_ids = []

    for i, chunk in enumerate(chunks):
        concept = f"docs:{source_key}:chunk{i+1}"
        chunk_content = f"[source: {source}]\n\n{chunk}"
        chunk_tags = tags + ["documentation", "ingested"]

        try:
            engram_id = await client.store(concept=concept, content=chunk_content, tags=chunk_tags)
            if engram_id:
                engram_ids.append(str(engram_id))
        except Exception as e:
            log.warning("Failed to store chunk %d for %s: %s", i, source_key, e)

    # Parallel write to pgvector (sync, best-effort)
    if platform and chunks:
        log.info("pgvector parallel write: %d chunks for platform=%s", len(chunks), platform)
        try:
            from api.rag.ingest import ingest_chunks
            ingest_chunks(
                chunks=chunks,
                platform=platform,
                doc_type=doc_type,
                source_url=source,
                source_label=source_key,
            )
        except Exception as e:
            log.debug("pgvector ingest skipped for %s: %s", source_key, e)

    return engram_ids


async def ingest(
    source_url: Optional[str] = None,
    local_file_path: Optional[str] = None,
    tags: list[str] = None,
    source_label: Optional[str] = None,
) -> dict:
    """
    Full ingest pipeline: fetch/parse → diff check → store locally → store in MuninnDB.
    Returns result including preview, diff info, and engram IDs.
    """
    if tags is None:
        tags = []

    if source_url:
        source_key = _url_key(source_url)
        source_label = source_label or source_url
        try:
            _, content = await fetch_url(source_url)
        except Exception as e:
            return {"status": "error", "message": f"Failed to fetch URL: {e}"}
        suffix = ".txt"
        orig_suffix = ".html"
    elif local_file_path:
        path = Path(local_file_path)
        source_key = re.sub(r'[^\w.-]', '_', path.name)[:80]
        source_label = source_label or path.name
        try:
            content = parse_pdf(local_file_path)
        except Exception as e:
            return {"status": "error", "message": f"Failed to parse PDF: {e}"}
        suffix = ".txt"
        orig_suffix = ".pdf"
    else:
        return {"status": "error", "message": "Either source_url or local_file_path required"}

    # Check for updates
    update_info = check_if_updated(source_key, content)

    # Save locally
    local_path = _save_local(source_key, content, suffix)

    # Detect platform/doc_type for pgvector parallel write
    _rag_platform, _rag_doc_type = "", "admin_guide"
    if source_url:
        try:
            from api.rag.ingest import detect_platform_from_url
            _rag_platform, _rag_doc_type = detect_platform_from_url(source_url)
        except Exception:
            pass
    log.info("pgvector ingest: platform=%s doc_type=%s source=%s",
             _rag_platform or "(none)", _rag_doc_type, (source_url or local_file_path or "")[:80])

    # Store in MuninnDB + pgvector
    engram_ids = await chunk_and_store(
        content=content,
        source=source_label,
        tags=tags + (["url"] if source_url else ["pdf"]),
        source_key=source_key,
        local_path=local_path,
        platform=_rag_platform,
        doc_type=_rag_doc_type,
    )

    # Update manifest
    manifest = _load_manifest()
    manifest[source_key] = {
        "source_url": source_url,
        "source_label": source_label,
        "local_path": local_path,
        "content_hash": update_info["new_hash"],
        "muninndb_ids": engram_ids,
        "stored_at": _ts(),
        "chunk_count": len(engram_ids),
    }
    _save_manifest(manifest)

    # Breaking changes analysis (if update)
    breaking_changes = None
    llm_analysis = None
    if update_info["is_updated"] and update_info.get("diff_snippet"):
        breaking_changes = update_info["diff_snippet"]
        llm_analysis = await detect_breaking_changes_llm(
            update_info["diff_snippet"], source_label
        )

    return {
        "status": "ok",
        "source_key": source_key,
        "source_label": source_label,
        "local_path": local_path,
        "engram_ids": engram_ids,
        "chunk_count": len(engram_ids),
        "is_new": update_info["is_new"],
        "is_updated": update_info["is_updated"],
        "content_hash": update_info["new_hash"],
        "preview": content[:600],
        "breaking_changes_diff": breaking_changes,
        "breaking_changes_llm": llm_analysis,
        "message": (
            f"Ingested {len(engram_ids)} chunk(s) from {source_label}"
            + (" [NEW]" if update_info["is_new"] else " [UPDATED]" if update_info["is_updated"] else " [UNCHANGED]")
        ),
    }


async def check_internet_connectivity() -> dict:
    """Check if internet is accessible."""
    import httpx
    test_urls = [
        ("https://1.1.1.1", 5),
        ("https://google.com", 5),
    ]
    import time
    for url, timeout in test_urls:
        try:
            t0 = time.monotonic()
            async with httpx.AsyncClient(timeout=timeout) as client:
                await client.head(url)
            latency_ms = int((time.monotonic() - t0) * 1000)
            return {"online": True, "latency_ms": latency_ms, "via": url}
        except Exception:
            continue
    return {"online": False, "latency_ms": None, "via": None}
