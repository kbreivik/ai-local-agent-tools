#!/usr/bin/env bash
# Initialize Docker Swarm — manager-01 leads, others join. Idempotent.
set -euo pipefail
source "$(dirname "$0")/vars.sh"

_ssh() { ssh $SSH_OPTS "$SSH_USER@$1" "$2"; }

echo "=== Initializing Swarm on $MANAGER_01 ==="
SWARM_STATE=$(_ssh "$MANAGER_01" "docker info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null || echo inactive")

if [ "$SWARM_STATE" = "active" ]; then
    echo "Swarm already active on $MANAGER_01"
else
    _ssh "$MANAGER_01" "docker swarm init --advertise-addr $MANAGER_01"
fi

MANAGER_TOKEN=$(_ssh "$MANAGER_01" "docker swarm join-token manager -q")
WORKER_TOKEN=$(_ssh "$MANAGER_01" "docker swarm join-token worker -q")

for node in $MANAGER_02 $MANAGER_03; do
    echo "=== Joining manager: $node ==="
    STATE=$(_ssh "$node" "docker info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null || echo inactive")
    if [ "$STATE" = "active" ]; then
        echo "$node already in swarm"
    else
        _ssh "$node" "docker swarm join --token $MANAGER_TOKEN $MANAGER_01:2377"
    fi
done

for node in $WORKER_NODES; do
    echo "=== Joining worker: $node ==="
    STATE=$(_ssh "$node" "docker info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null || echo inactive")
    if [ "$STATE" = "active" ]; then
        echo "$node already in swarm"
    else
        _ssh "$node" "docker swarm join --token $WORKER_TOKEN $MANAGER_01:2377"
    fi
done

echo ""
_ssh "$MANAGER_01" "docker node ls"
echo ""
echo "Done — Swarm ready."
