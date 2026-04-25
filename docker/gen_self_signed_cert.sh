#!/usr/bin/env bash
# Generate a self-signed cert + key for nginx TLS proxy.
# For dev / homelab use only. For production, use Let's Encrypt or internal CA.
#
# Usage:
#   bash docker/gen_self_signed_cert.sh [hostname]
#
# Default hostname: agent-01.lan

set -euo pipefail

HOSTNAME="${1:-agent-01.lan}"
CERT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/certs"

mkdir -p "$CERT_DIR"

if [[ -f "$CERT_DIR/server.crt" && -f "$CERT_DIR/server.key" ]]; then
    echo "[gen-cert] $CERT_DIR already has server.crt + server.key"
    echo "[gen-cert] Delete them first if you want to regenerate."
    exit 0
fi

openssl req -x509 -nodes -newkey rsa:4096 \
    -keyout "$CERT_DIR/server.key" \
    -out    "$CERT_DIR/server.crt" \
    -days 825 \
    -subj "/CN=${HOSTNAME}/O=DEATHSTAR/OU=homelab" \
    -addext "subjectAltName=DNS:${HOSTNAME},DNS:localhost,IP:127.0.0.1,IP:192.168.199.10"

chmod 600 "$CERT_DIR/server.key"
chmod 644 "$CERT_DIR/server.crt"

echo "[gen-cert] Wrote $CERT_DIR/server.crt and server.key"
echo "[gen-cert] Mount this directory into the nginx container as /etc/nginx/certs:ro"
echo "[gen-cert] Then set HP1_BEHIND_HTTPS=true in docker/.env and restart hp1_agent."
