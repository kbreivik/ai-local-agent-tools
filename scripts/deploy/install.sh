#!/usr/bin/env bash
# DEATHSTAR — Full infrastructure deploy
# Run from repo root: bash scripts/deploy/install.sh
#
# Prerequisites:
#   1. Copy scripts/deploy/vars.sh.example -> vars.sh and edit
#   2. SSH key in $SSH_KEY with no passphrase (or ssh-agent loaded)
#   3. VMs reachable and $SSH_USER has sudo
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -f "$SCRIPT_DIR/vars.sh" ]; then
    echo "ERROR: vars.sh not found."
    echo "Copy $SCRIPT_DIR/vars.sh.example -> $SCRIPT_DIR/vars.sh and edit it."
    exit 1
fi
source "$SCRIPT_DIR/vars.sh"

echo "======================================"
echo "  DEATHSTAR — Infrastructure Deploy   "
echo "======================================"
echo ""
echo "Nodes: managers=$MANAGER_01,$MANAGER_02,$MANAGER_03"
echo "       workers=$WORKER_01,$WORKER_02,$WORKER_03"
echo "       agent=$AGENT_01"
echo ""
read -p "Proceed? (y/N) " confirm
[ "$confirm" = "y" ] || { echo "Aborted."; exit 0; }

echo ""
echo "Step 1/3: Install Docker + configure TCP + sudo..."
bash "$SCRIPT_DIR/01_docker_install.sh"

echo ""
echo "Step 2/3: Initialize Docker Swarm..."
bash "$SCRIPT_DIR/02_swarm_init.sh"

echo ""
echo "Step 3/3: Register connections in DEATHSTAR..."
echo "(Waiting 10s for agent to be ready...)"
sleep 10
bash "$SCRIPT_DIR/03_register_connections.sh"

echo ""
echo "======================================"
echo "  Deploy complete                     "
echo "======================================"
echo ""
echo "Dashboard: http://$AGENT_01:8000"
echo "VM Hosts and Docker connections are now registered."
echo "Collectors will populate the dashboard within ~60 seconds."
