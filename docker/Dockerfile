# ── Stage 1: Build ──────────────────────────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /build

# System deps needed to compile wheels (paramiko, bcrypt, cryptography)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev libssl-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# ── Stage 2: Runtime ────────────────────────────────────────────────────────
FROM python:3.13-slim

LABEL org.opencontainers.image.title="HP1-AI-Agent" \
      org.opencontainers.image.description="Self-improving AI infrastructure agent" \
      org.opencontainers.image.source="https://github.com/kbreivik/ai-local-agent-tools"

# Runtime system deps only — no compiler
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl openssh-client jq && \
    rm -rf /var/lib/apt/lists/*

# Non-root user with Docker group access.
# GID 998 is common for docker group on Linux — override with --build-arg DOCKER_GID
ARG DOCKER_GID=998
RUN groupadd -g ${DOCKER_GID} dockersock 2>/dev/null || true && \
    useradd -m -s /bin/bash agent && \
    usermod -aG dockersock agent 2>/dev/null || true

# Install Python wheels from builder (all deps, no pip at runtime)
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels

# Copy application code
WORKDIR /app
COPY . .

# Data directories — overlaid by volume mounts at runtime
RUN mkdir -p \
    data/skill_exports \
    data/skill_imports \
    data/docs \
    logs \
    checkpoints \
    mcp_server/tools/skills/modules && \
    chown -R agent:agent /app

# Entrypoint and healthcheck scripts
COPY docker/entrypoint.sh /entrypoint.sh
COPY docker/healthcheck.sh /healthcheck.sh
RUN chmod +x /entrypoint.sh /healthcheck.sh

# API port (MCP stdio is internal — no separate port needed)
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD /healthcheck.sh

USER agent
ENTRYPOINT ["/entrypoint.sh"]
