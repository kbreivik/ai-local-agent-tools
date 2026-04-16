#!/usr/bin/env bash
# Verify a DEATHSTAR backup bundle WITHOUT restoring.
#
# Checks:
#   1. Bundle extracts cleanly.
#   2. manifest.json matches actual sha256 of every file.
#   3. Fingerprint stored in fingerprint.txt matches the fingerprint derived
#      from env.backup (or env.backup.age after the operator decrypts it).
#   4. db.dump is a valid pg_dump custom-format file (pg_restore --list).
#
# USAGE
#   bash scripts/deathstar-verify-bundle.sh /path/to/deathstar-host-TS.tar.gz
#   bash scripts/deathstar-verify-bundle.sh /path/to/bundle.tar.gz --age-key ~/.age/key.txt

set -euo pipefail

BUNDLE="${1:-}"
[[ -f "$BUNDLE" ]] || { echo "Usage: $0 <bundle.tar.gz> [--age-key FILE]" >&2; exit 2; }
shift || true

AGE_KEY=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --age-key) AGE_KEY="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

log() { printf '%s [verify] %s\n' "$(date -Is)" "$*"; }
die() { log "FAIL: $*" >&2; exit 1; }

log "Extracting $BUNDLE"
tar -C "$WORK" -xzf "$BUNDLE"

cd "$WORK"
[[ -f manifest.json ]] || die "manifest.json missing"
[[ -f fingerprint.txt ]] || die "fingerprint.txt missing"
[[ -f db.dump ]] || die "db.dump missing"

# Re-check every sha in manifest
python3 - <<'PY'
import json, hashlib, sys
m = json.load(open("manifest.json"))
for f in m["files"]:
    h = hashlib.sha256(open(f["name"], "rb").read()).hexdigest()
    assert h == f["sha256"], f"sha mismatch for {f['name']}: manifest={f['sha256']} actual={h}"
    assert sum(1 for _ in open(f["name"], "rb")) >= 0  # just proves readable
print("manifest sha OK (%d files)" % len(m["files"]))
PY

STORED_FP="$(grep -oE '"fingerprint":"[^"]+"' fingerprint.txt | head -1 | sed 's/.*:"//; s/"$//')"
[[ -n "$STORED_FP" ]] || die "stored fingerprint missing"
log "Stored fingerprint: $STORED_FP"

# Derive fingerprint from env.backup (decrypting age if needed)
ENV_PLAIN=""
if [[ -f env.backup ]]; then
  ENV_PLAIN="env.backup"
elif [[ -f env.backup.age ]]; then
  [[ -n "$AGE_KEY" && -f "$AGE_KEY" ]] || die "env.backup.age present but --age-key not given"
  age -d -i "$AGE_KEY" -o env.backup env.backup.age
  ENV_PLAIN="env.backup"
else
  die "no env.backup{,.age} in bundle"
fi

KEY_VALUE="$(grep -E '^SETTINGS_ENCRYPTION_KEY=' "$ENV_PLAIN" | sed -E 's/^SETTINGS_ENCRYPTION_KEY=//; s/^"//; s/"$//')"
[[ -n "$KEY_VALUE" ]] || die "SETTINGS_ENCRYPTION_KEY missing from env.backup"
DERIVED_FP="$(printf '%s' "$KEY_VALUE" | sha256sum | cut -c1-8)"

if [[ "$STORED_FP" != "$DERIVED_FP" ]]; then
  die "FINGERPRINT MISMATCH — stored=$STORED_FP derived=$DERIVED_FP. This bundle's .env does not match its db.dump."
fi
log "Fingerprint match: $STORED_FP"

# pg_dump format sanity
if command -v pg_restore >/dev/null 2>&1; then
  if pg_restore --list db.dump >/dev/null 2>&1; then
    log "db.dump is a valid Postgres custom-format dump."
  else
    die "db.dump failed pg_restore --list (file may be truncated or corrupt)."
  fi
else
  log "pg_restore not installed on this host — skipping dump format check."
fi

log "Bundle verified OK."
