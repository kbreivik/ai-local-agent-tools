#!/usr/bin/env bash
# DEATHSTAR backup — dumps Postgres, captures .env, records key fingerprint.
#
# USAGE
#   Run on the agent-01 host (NOT inside the container — we need access to
#   /opt/hp1-agent/docker/.env and the Docker socket):
#
#     sudo bash scripts/deathstar-backup.sh [--out /var/backups/deathstar]
#                                           [--age-recipient age1xxx...]
#                                           [--retain 14]
#
#   Env var overrides:
#     DEATHSTAR_BACKUP_DIR        (default: /var/backups/deathstar)
#     DEATHSTAR_AGE_RECIPIENT     (default: empty — no encryption)
#     DEATHSTAR_RETAIN_DAYS       (default: 14)
#     DEATHSTAR_COMPOSE_DIR       (default: /opt/hp1-agent/docker)
#     DEATHSTAR_API_URL           (default: http://127.0.0.1:8000)
#     DEATHSTAR_AUTH_COOKIE_FILE  (default: /root/.deathstar-cookies)
#
#   For the fingerprint check to succeed, DEATHSTAR_AUTH_COOKIE_FILE must hold
#   a valid login cookie obtained via POST /api/auth/login. See the README
#   section "Preparing the backup cookie" below the script for the one-time
#   setup.
#
# BUNDLE LAYOUT  (inside deathstar-<host>-<ts>.tar.gz)
#   db.dump                 — pg_dump -Fc output
#   env.backup              — copy of docker/.env (plaintext unless --age-recipient)
#   env.backup.age          — present only if age encryption enabled
#   fingerprint.txt         — {"fingerprint":"XXXXXXXX","verified_via_api":true,
#                             "api_status":"ok","backup_at":"ISO8601","host":"..."}
#   VERSION                 — the API version string at backup time
#   manifest.json           — list of files + sha256 per file

set -euo pipefail

# ── Defaults ─────────────────────────────────────────────────────────────────
BACKUP_DIR="${DEATHSTAR_BACKUP_DIR:-/var/backups/deathstar}"
COMPOSE_DIR="${DEATHSTAR_COMPOSE_DIR:-/opt/hp1-agent/docker}"
API_URL="${DEATHSTAR_API_URL:-http://127.0.0.1:8000}"
COOKIE_FILE="${DEATHSTAR_AUTH_COOKIE_FILE:-/root/.deathstar-cookies}"
AGE_RECIPIENT="${DEATHSTAR_AGE_RECIPIENT:-}"
RETAIN_DAYS="${DEATHSTAR_RETAIN_DAYS:-14}"

# ── Args ─────────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --out)            BACKUP_DIR="$2"; shift 2 ;;
    --age-recipient)  AGE_RECIPIENT="$2"; shift 2 ;;
    --retain)         RETAIN_DAYS="$2"; shift 2 ;;
    --compose-dir)    COMPOSE_DIR="$2"; shift 2 ;;
    --api-url)        API_URL="$2"; shift 2 ;;
    --cookie-file)    COOKIE_FILE="$2"; shift 2 ;;
    -h|--help)        sed -n '2,/^set -euo/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

HOSTNAME_SHORT="$(hostname -s 2>/dev/null || hostname)"
TS="$(date -u +%Y-%m-%dT%H%M%SZ)"
BUNDLE_NAME="deathstar-${HOSTNAME_SHORT}-${TS}"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

log() { printf '%s [backup] %s\n' "$(date -Is)" "$*"; }
die() { log "FATAL: $*" >&2; exit 1; }

mkdir -p "$BACKUP_DIR"
[[ -w "$BACKUP_DIR" ]] || die "Backup dir not writable: $BACKUP_DIR"

# ── 1. Sanity checks ─────────────────────────────────────────────────────────
ENV_FILE="$COMPOSE_DIR/.env"
[[ -f "$ENV_FILE" ]] || die ".env not found at $ENV_FILE"

if ! command -v pg_dump >/dev/null 2>&1; then
  log "pg_dump not on host — will run it inside the hp1_agent container."
  PG_DUMP_MODE="container"
else
  PG_DUMP_MODE="host"
fi

# Load DATABASE_URL from .env (strip any surrounding quotes). Kept local; never
# exported so child processes don't accidentally inherit it.
DB_URL="$(grep -E '^DATABASE_URL=' "$ENV_FILE" | sed -E 's/^DATABASE_URL=//; s/^"//; s/"$//')"
[[ -n "$DB_URL" ]] || die "DATABASE_URL missing from $ENV_FILE"
# pg_dump wants postgresql://, not postgresql+asyncpg://
DB_URL_PG="$(echo "$DB_URL" | sed 's|postgresql+asyncpg://|postgresql://|')"

# ── 2. pg_dump ───────────────────────────────────────────────────────────────
DUMP_FILE="$WORK_DIR/db.dump"
log "Dumping Postgres → $DUMP_FILE"
if [[ "$PG_DUMP_MODE" == "host" ]]; then
  PGPASSWORD="" pg_dump -Fc "$DB_URL_PG" -f "$DUMP_FILE"
else
  # Run inside the container; write to stdout, capture on host.
  docker exec -i hp1_agent pg_dump -Fc "$DB_URL_PG" > "$DUMP_FILE"
fi
[[ -s "$DUMP_FILE" ]] || die "pg_dump produced an empty file"
log "pg_dump complete: $(stat -c%s "$DUMP_FILE") bytes"

# ── 3. Snapshot .env ─────────────────────────────────────────────────────────
ENV_COPY="$WORK_DIR/env.backup"
cp "$ENV_FILE" "$ENV_COPY"
chmod 600 "$ENV_COPY"

# ── 4. Derive & verify fingerprint ───────────────────────────────────────────
# Fingerprint = first 8 hex chars of SHA-256 of the raw SETTINGS_ENCRYPTION_KEY.
KEY_VALUE="$(grep -E '^SETTINGS_ENCRYPTION_KEY=' "$ENV_FILE" | sed -E 's/^SETTINGS_ENCRYPTION_KEY=//; s/^"//; s/"$//')"
[[ -n "$KEY_VALUE" ]] || die "SETTINGS_ENCRYPTION_KEY missing from $ENV_FILE"
LOCAL_FP="$(printf '%s' "$KEY_VALUE" | sha256sum | cut -c1-8)"

API_STATUS="unavailable"
API_FP=""
if [[ -f "$COOKIE_FILE" ]]; then
  RESP="$(curl -s --max-time 6 -b "$COOKIE_FILE" "$API_URL/api/status/health/crypto" || true)"
  if [[ -n "$RESP" ]] && echo "$RESP" | grep -q '"fingerprint"'; then
    API_STATUS="$(echo "$RESP" | sed -E 's/.*"status":"([^"]+)".*/\1/')"
    API_FP="$(echo "$RESP" | sed -E 's/.*"fingerprint":"([^"]+)".*/\1/')"
  fi
fi

if [[ -n "$API_FP" && "$API_FP" != "$LOCAL_FP" ]]; then
  die "Fingerprint mismatch — API says '$API_FP', .env-derived is '$LOCAL_FP'. Refusing to write a bundle that can't be verified on restore."
fi

# ── 5. Version ───────────────────────────────────────────────────────────────
VERSION="unknown"
V_RESP="$(curl -s --max-time 4 "$API_URL/api/health" || true)"
if [[ -n "$V_RESP" ]]; then
  VERSION="$(echo "$V_RESP" | sed -E 's/.*"version":"([^"]+)".*/\1/')"
fi
echo "$VERSION" > "$WORK_DIR/VERSION"

# ── 6. fingerprint.txt ───────────────────────────────────────────────────────
cat > "$WORK_DIR/fingerprint.txt" <<EOF
{"fingerprint":"$LOCAL_FP","verified_via_api":$( [[ -n "$API_FP" ]] && echo true || echo false ),"api_status":"$API_STATUS","backup_at":"$(date -Is)","host":"$HOSTNAME_SHORT","version":"$VERSION"}
EOF

# ── 7. Optional age encryption of env.backup ─────────────────────────────────
if [[ -n "$AGE_RECIPIENT" ]]; then
  command -v age >/dev/null 2>&1 || die "--age-recipient set but 'age' is not installed on this host"
  log "Encrypting env.backup with age recipient $AGE_RECIPIENT"
  age -r "$AGE_RECIPIENT" -o "$WORK_DIR/env.backup.age" "$ENV_COPY"
  shred -u "$ENV_COPY" 2>/dev/null || rm -f "$ENV_COPY"
fi

# ── 8. manifest.json ─────────────────────────────────────────────────────────
(
  cd "$WORK_DIR"
  {
    printf '{\n  "files": ['
    first=1
    for f in *; do
      [[ "$f" == "manifest.json" ]] && continue
      sha="$(sha256sum "$f" | awk '{print $1}')"
      size="$(stat -c%s "$f")"
      [[ $first -eq 0 ]] && printf ','
      printf '\n    {"name":"%s","sha256":"%s","size":%d}' "$f" "$sha" "$size"
      first=0
    done
    printf '\n  ],\n  "fingerprint": "%s",\n  "version": "%s",\n  "backup_at": "%s"\n}\n' \
      "$LOCAL_FP" "$VERSION" "$(date -Is)"
  } > manifest.json
)

# ── 9. Tar + move into place ─────────────────────────────────────────────────
OUT="$BACKUP_DIR/${BUNDLE_NAME}.tar.gz"
tar -C "$WORK_DIR" -czf "$OUT" .
chmod 600 "$OUT"
log "Wrote $OUT ($(stat -c%s "$OUT") bytes)"

# ── 10. Retention ────────────────────────────────────────────────────────────
if [[ "$RETAIN_DAYS" =~ ^[0-9]+$ && "$RETAIN_DAYS" -gt 0 ]]; then
  log "Pruning bundles older than ${RETAIN_DAYS}d in $BACKUP_DIR"
  find "$BACKUP_DIR" -maxdepth 1 -type f -name 'deathstar-*.tar.gz' \
    -mtime +"$RETAIN_DAYS" -print -delete || true
fi

log "Backup complete."
echo "$OUT"
