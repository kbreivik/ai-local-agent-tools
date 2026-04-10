#!/usr/bin/env bash
# Install Docker + configure TCP socket on all nodes. Idempotent.
set -euo pipefail
source "$(dirname "$0")/vars.sh"

_ssh() { ssh $SSH_OPTS "$SSH_USER@$1" "$2"; }

install_docker() {
    local node=$1
    echo "=== Installing Docker on $node ==="
    _ssh "$node" "
        if command -v docker &>/dev/null; then
            echo 'Docker already installed'
            docker --version
            exit 0
        fi
        curl -fsSL https://get.docker.com | sudo sh
        sudo usermod -aG docker \$USER
        sudo systemctl enable --now docker
        docker --version
    "
    if [ "${DOCKER_EXPOSE_TCP:-}" = "true" ]; then
        echo "Configuring TCP socket on $node..."
        _ssh "$node" "
            sudo mkdir -p /etc/systemd/system/docker.service.d
            cat | sudo tee /etc/systemd/system/docker.service.d/tcp.conf <<'EOF'
[Service]
ExecStart=
ExecStart=/usr/bin/dockerd -H fd:// -H tcp://0.0.0.0:2375
EOF
            sudo systemctl daemon-reload
            sudo systemctl restart docker
        "
    fi
    echo "Configuring passwordless sudo..."
    _ssh "$node" "
        echo '$SSH_USER ALL=(ALL) NOPASSWD: /usr/bin/apt-get, /sbin/shutdown, /bin/systemctl' \
            | sudo tee /etc/sudoers.d/deathstar-ops
        sudo chmod 440 /etc/sudoers.d/deathstar-ops
    "
}

for node in $ALL_NODES; do
    install_docker "$node"
done
echo ""
echo "Done — Docker installed on all nodes."
