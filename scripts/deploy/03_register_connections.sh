#!/usr/bin/env bash
# Register all infrastructure connections in DEATHSTAR. Idempotent.
set -euo pipefail
source "$(dirname "$0")/vars.sh"

AGENT_URL="http://$AGENT_01:8000"

echo "Authenticating with DEATHSTAR at $AGENT_URL..."
TOKEN=$(curl -sf -X POST "$AGENT_URL/api/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"admin\",\"password\":\"$DEATHSTAR_ADMIN_PASSWORD\"}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))")

if [ -z "$TOKEN" ]; then
    echo "ERROR: Could not authenticate. Is the agent running?"
    exit 1
fi

_register() {
    local platform=$1 label=$2 host=$3 port=$4 auth_type=$5
    local creds=$6
    local config=${7:-'{}'}

    EXISTS=$(curl -sf "$AGENT_URL/api/connections?platform=$platform" \
        -H "Authorization: Bearer $TOKEN" \
        | python3 -c "
import sys,json
data = json.load(sys.stdin).get('data',[])
print('yes' if any(d.get('label')=='$label' for d in data) else 'no')
")
    if [ "$EXISTS" = "yes" ]; then
        echo "  skip: $platform/$label (exists)"
        return 0
    fi

    BODY=$(python3 -c "
import json
print(json.dumps({
    'platform': '$platform', 'label': '$label', 'host': '$host',
    'port': $port, 'auth_type': '$auth_type',
    'credentials': $creds, 'config': $config,
}))
")
    curl -sf -X POST "$AGENT_URL/api/connections" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d "$BODY" > /dev/null
    echo "  registered: $platform/$label -> $host:$port"
}

SSH_KEY_ESCAPED=$(python3 -c "import sys; print(open('$SSH_KEY').read().replace(chr(10), r'\n'))")

echo ""
echo "=== Registering VM hosts ==="
for pair in "manager-01:$MANAGER_01:swarm_manager" "manager-02:$MANAGER_02:swarm_manager" \
            "manager-03:$MANAGER_03:swarm_manager" "worker-01:$WORKER_01:swarm_worker" \
            "worker-02:$WORKER_02:swarm_worker" "worker-03:$WORKER_03:swarm_worker"; do
    IFS=: read -r label ip role <<< "$pair"
    _register vm_host "$label" "$ip" 22 ssh \
        "{\"username\":\"$SSH_USER\",\"private_key\":\"$SSH_KEY_ESCAPED\",\"role\":\"$role\"}"
done

echo ""
echo "=== Registering Docker hosts ==="
_register docker_host "manager-01-docker" "$MANAGER_01" 2375 tcp '{}' '{"role":"swarm_manager"}'
for node_pair in "worker-01:$WORKER_01" "worker-02:$WORKER_02" "worker-03:$WORKER_03"; do
    IFS=: read -r label ip <<< "$node_pair"
    _register docker_host "$label-docker" "$ip" 2375 tcp '{}' '{"role":"swarm_worker"}'
done

echo ""
echo "Done — all connections registered. Dashboard populates within 60s."
