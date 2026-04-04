"""Embed and upsert document chunks into pgvector doc_chunks table.

All functions are synchronous (project rule). Uses psycopg2 directly.
Ingestion is idempotent — ON CONFLICT (platform, source_url, chunk_index) DO UPDATE.
"""
import logging
import os
from urllib.parse import urlparse

from api.rag.doc_search import embed

log = logging.getLogger(__name__)

# ── URL-to-platform auto-detection ───────────────────────────────────────────

DOMAIN_PLATFORM_MAP = {
    "pve.proxmox.com": ("proxmox", "admin_guide"),
    "docs.fortinet.com": ("fortigate", "admin_guide"),
    "docs.truenas.com": ("truenas", "admin_guide"),
    "docs.pi-hole.net": ("pihole", "admin_guide"),
    "documentation.wazuh.com": ("wazuh", "admin_guide"),
    "docs.securityonion.net": ("security_onion", "admin_guide"),
    "caddyserver.com": ("caddy", "admin_guide"),
    "doc.traefik.io": ("traefik", "admin_guide"),
    "docs.ansible.com": ("ansible", "api_reference"),
    "registry.terraform.io": ("terraform", "api_reference"),
    "docs.netbox.dev": ("netbox", "api_reference"),
    "nginx.org": ("nginx", "admin_guide"),
    "docs.syncthing.net": ("syncthing", "admin_guide"),
    "technitium.com": ("technitium", "admin_guide"),
}


def detect_platform_from_url(url: str) -> tuple[str, str]:
    """Return (platform, doc_type) from URL domain, or ("", "") if unknown."""
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return ("", "")
    # Try exact match first, then suffix match
    for domain, result in DOMAIN_PLATFORM_MAP.items():
        if host == domain or host.endswith("." + domain):
            return result
    return ("", "")


# ── Upsert pipeline ─────────────────────────────────────────────────────────

_UPSERT_SQL = """
INSERT INTO doc_chunks (content, embedding, platform, doc_type, source_url, source_label, version, chunk_index)
VALUES (%(content)s, %(embedding)s, %(platform)s, %(doc_type)s, %(source_url)s, %(source_label)s, %(version)s, %(chunk_index)s)
ON CONFLICT (platform, source_url, chunk_index) DO UPDATE SET
    content = EXCLUDED.content,
    embedding = EXCLUDED.embedding,
    doc_type = EXCLUDED.doc_type,
    source_label = EXCLUDED.source_label,
    version = EXCLUDED.version,
    created_at = NOW()
"""


def ingest_chunks(
    chunks: list[str],
    platform: str,
    doc_type: str,
    source_url: str = "",
    source_label: str = "",
    version: str = "",
) -> int:
    """Embed and upsert chunks into doc_chunks table.

    Returns number of rows upserted. Returns 0 if PostgreSQL unavailable.
    """
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        return 0

    if not chunks:
        return 0

    try:
        import psycopg2
        import numpy as np
        from pgvector.psycopg2 import register_vector as _register_vector
    except ImportError as e:
        log.warning("RAG ingest: missing dependency: %s", e)
        return 0

    try:
        dsn = database_url.replace("postgresql+asyncpg://", "postgresql://")
        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        _register_vector(conn)
        conn.autocommit = False
        cur = conn.cursor()

        count = 0
        for i, chunk in enumerate(chunks):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                vec = np.array(embed(chunk), dtype=np.float32)
                cur.execute(_UPSERT_SQL, {
                    "content": chunk,
                    "embedding": vec,
                    "platform": platform,
                    "doc_type": doc_type,
                    "source_url": source_url,
                    "source_label": source_label,
                    "version": version,
                    "chunk_index": i,
                })
                count += 1
            except Exception as e:
                log.warning("RAG ingest chunk %d failed: %s", i, e)

        conn.commit()
        cur.close()
        conn.close()
        log.info("RAG ingest: %d/%d chunks upserted (platform=%s, source=%s)",
                 count, len(chunks), platform, source_url[:80])
        return count

    except Exception as e:
        log.warning("RAG ingest failed: %s", e)
        return 0
