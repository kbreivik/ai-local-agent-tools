#!/usr/bin/env python3
"""Rotate the Fernet encryption key used for secrets in the DEATHSTAR database.

USAGE (run inside the container, or via `docker run` against the image):

  # 1. Generate a new key
  docker exec hp1_agent python -c \\
      "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

  # 2. Stop the agent container so nothing reads/writes during rotation.
  cd /opt/hp1-agent/docker && docker compose stop hp1_agent

  # 3. Dry-run first (no writes):
  docker run --rm --network=docker_default \\
    --env-file /opt/hp1-agent/docker/.env \\
    ghcr.io/kbreivik/hp1-ai-agent:latest \\
    python -m scripts.rotate_encryption_key \\
      --old "$OLD_KEY" --new "$NEW_KEY" --dry-run --yes

  # 4. Real rotation:
  docker run --rm --network=docker_default \\
    --env-file /opt/hp1-agent/docker/.env \\
    ghcr.io/kbreivik/hp1-ai-agent:latest \\
    python -m scripts.rotate_encryption_key \\
      --old "$OLD_KEY" --new "$NEW_KEY" --yes

  # 5. Update SETTINGS_ENCRYPTION_KEY in docker/.env to the new key.
  # 6. Start hp1_agent. Verify /api/status/health/crypto returns status=ok
  #    with the NEW fingerprint.

SAFETY:
  * Requires --old to successfully decrypt the crypto_canary row BEFORE any
    re-encryption. Aborts with exit 3 if the old key is wrong.
  * Single transaction. Any failure rolls back. No partial state.
  * After re-encrypting, reseeds the canary under --new and verifies round-trip
    BEFORE COMMIT. If that fails, the transaction rolls back.
  * --dry-run rolls back the transaction after the full in-memory plan runs.
"""

from __future__ import annotations
import argparse
import logging
import os
import sys
from typing import Iterable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.crypto import (  # noqa: E402
    decrypt_with_key,
    encrypt_with_key,
    fingerprint_of_key,
    is_encrypted,
    _PREFIX,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("rotate_encryption_key")

KNOWN_TARGETS: list[tuple[str, str, str]] = [
    ("connections",         "id", "credentials"),
    ("credential_profiles", "id", "credentials"),
    ("crypto_canary",       "id", "encrypted_value"),
]


def _connect():
    dsn = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
    if not dsn:
        log.error("DATABASE_URL not set. This script requires Postgres.")
        sys.exit(2)
    import psycopg2
    return psycopg2.connect(dsn)


def _discover_targets(cur) -> list[tuple[str, str, str]]:
    """Scan information_schema for public TEXT columns holding enc::-prefixed rows."""
    cur.execute("""
        SELECT c.table_name, c.column_name
          FROM information_schema.columns c
         WHERE c.table_schema = 'public'
           AND c.data_type IN ('text', 'character varying')
    """)
    known = {(t, col) for t, _, col in KNOWN_TARGETS}
    out: list[tuple[str, str, str]] = []
    for table, column in cur.fetchall():
        if (table, column) in known:
            continue
        try:
            cur.execute(
                f"SELECT 1 FROM {table} WHERE {column} LIKE %s LIMIT 1",
                (f"{_PREFIX}%",),
            )
            if not cur.fetchone():
                continue
        except Exception:
            continue
        cur.execute("""
            SELECT kcu.column_name
              FROM information_schema.table_constraints tc
              JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
             WHERE tc.table_name = %s
               AND tc.constraint_type = 'PRIMARY KEY'
             ORDER BY kcu.ordinal_position
             LIMIT 1
        """, (table,))
        row = cur.fetchone()
        pk = row[0] if row else "id"
        log.info("Discovered extra target: %s.%s (pk=%s)", table, column, pk)
        out.append((table, pk, column))
    return out


def _verify_canary(cur, old_key: str) -> bool:
    cur.execute("SELECT encrypted_value FROM crypto_canary WHERE id = 1")
    row = cur.fetchone()
    if not row or not row[0]:
        log.error("crypto_canary row not found. Refusing to rotate without a "
                  "canary. Start the service once with the current key (seeds "
                  "the canary), then retry.")
        return False
    try:
        plaintext = decrypt_with_key(row[0], old_key)
    except Exception as e:
        log.error("Old key could not decrypt crypto_canary: %s", e)
        return False
    if plaintext != "DEATHSTAR_CRYPTO_CANARY_v1":
        log.error("Canary plaintext mismatch — old key is wrong.")
        return False
    log.info("Old key validated (fingerprint=%s).", fingerprint_of_key(old_key))
    return True


def _plan(cur, old_key: str, targets: Iterable[tuple[str, str, str]]):
    plan: list = []
    failures: list[str] = []
    for table, pk, col in targets:
        cur.execute(f"SELECT {pk}, {col} FROM {table} WHERE {col} LIKE %s",
                    (f"{_PREFIX}%",))
        rows = cur.fetchall()
        log.info("  %s.%s: %d encrypted row(s)", table, col, len(rows))
        for pk_val, ciphertext in rows:
            if not is_encrypted(ciphertext):
                continue
            try:
                plan.append((table, pk, col, pk_val, decrypt_with_key(ciphertext, old_key)))
            except Exception as e:
                failures.append(f"{table}.{col} pk={pk_val}: {e}")
    return plan, failures


def _apply(cur, plan, new_key: str) -> int:
    for table, pk, col, pk_val, plaintext in plan:
        cur.execute(
            f"UPDATE {table} SET {col} = %s WHERE {pk} = %s",
            (encrypt_with_key(plaintext, new_key), pk_val),
        )
    return len(plan)


def _reseed_canary(cur, new_key: str) -> None:
    fresh = encrypt_with_key("DEATHSTAR_CRYPTO_CANARY_v1", new_key)
    cur.execute("UPDATE crypto_canary SET encrypted_value = %s WHERE id = 1", (fresh,))
    cur.execute("SELECT encrypted_value FROM crypto_canary WHERE id = 1")
    stored = cur.fetchone()[0]
    if decrypt_with_key(stored, new_key) != "DEATHSTAR_CRYPTO_CANARY_v1":
        raise RuntimeError("Canary round-trip failed — aborting.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true", help="Skip interactive confirm.")
    args = ap.parse_args()

    if args.old == args.new:
        log.error("--old and --new are identical.")
        return 2

    log.info("Old key fingerprint: %s", fingerprint_of_key(args.old))
    log.info("New key fingerprint: %s", fingerprint_of_key(args.new))
    log.info("Mode: %s", "DRY-RUN" if args.dry_run else "APPLY")

    conn = _connect()
    conn.autocommit = False
    cur = conn.cursor()
    try:
        if not _verify_canary(cur, args.old):
            return 3
        targets = list(KNOWN_TARGETS) + _discover_targets(cur)
        log.info("Targets (%d):", len(targets))
        for t, pk, c in targets:
            log.info("  - %s.%s (pk=%s)", t, c, pk)

        plan, failures = _plan(cur, args.old, targets)
        if failures:
            log.error("Old key failed to decrypt %d row(s):", len(failures))
            for f in failures[:10]:
                log.error("  %s", f)
            conn.rollback()
            return 4
        log.info("Planned %d re-encryption(s).", len(plan))

        if not args.yes and not args.dry_run:
            answer = input(f"Re-encrypt {len(plan)} row(s) under "
                           f"{fingerprint_of_key(args.new)}? [ROTATE to proceed]: ").strip()
            if answer != "ROTATE":
                log.info("Not confirmed. Rolling back.")
                conn.rollback()
                return 0

        written = _apply(cur, plan, args.new)
        log.info("Re-encrypted %d row(s).", written)

        _reseed_canary(cur, args.new)
        log.info("Canary reseeded under new key (fingerprint=%s).",
                 fingerprint_of_key(args.new))

        if args.dry_run:
            conn.rollback()
            log.info("DRY-RUN complete. Transaction rolled back.")
            return 0

        conn.commit()
        log.info("COMMIT complete. %d row(s) under %s.",
                 written, fingerprint_of_key(args.new))
        log.info("Next: update SETTINGS_ENCRYPTION_KEY in docker/.env and restart.")
        return 0

    except Exception as e:
        log.exception("Rotation failed: %s", e)
        conn.rollback()
        return 1
    finally:
        try:
            cur.close(); conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
