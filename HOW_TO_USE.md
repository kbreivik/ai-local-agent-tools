# HP1-AI-Agent-v1 — How To Use

## Prerequisites
```bash
# 1. Install Claude Code
npm install -g @anthropic-ai/claude-code

# 2. Install jcodemunch
pip install git+https://github.com/jgravelle/jcodemunch-mcp.git

# 3. Install MuninnDB (Phase 5+)
curl -fsSL https://muninndb.com/install.sh | sh && muninn init

# 4. LM Studio — load model:
#    lmstudio-community/qwen3-coder-30b-a3b-instruct
#    Enable server on localhost:1234
```

---

## First Time Setup

```bash
# 1. Clone / create project folder
cd D:/claude_code/FAJK/HP1-AI-Agent-v1

# 2. Create permissions folder
mkdir .claude

# 3. Copy config files from outputs:
#    .mcp.json          → project root
#    .claude/settings.json → .claude/
#    .env.example       → .env  (fill in your IPs)

# 4. Install Python deps
pip install -r requirements.txt

# 5. Start infrastructure
docker compose -f docker/docker-compose.yml up -d
```

---

## Running the Agent

```bash
# Start everything (API + GUI)
start.bat

# GUI available at:
http://<your-ip>:5173

# API available at:
http://<your-ip>:8000
```

---

## Starting Claude Code

```bash
cd D:/claude_code/FAJK/HP1-AI-Agent-v1

# Run with full autonomy (no confirmation prompts)
claude --dangerously-skip-permissions
```

---

## Building Each Phase

Open `ROADMAP.md` → find the phase → copy the prompt block → paste into Claude Code.

| Phase | What you get | Run this first |
|-------|-------------|----------------|
| 1-2 | GUI + FastAPI + Tool Registry | `docker compose up` |
| 3 | PostgreSQL logging | Postgres container running |
| 4 | Live Swarm + Kafka status | Swarm initialized, Kafka running |
| 5 | MuninnDB memory + RAG | MuninnDB container running |
| 6 | Filebeat + Elasticsearch logs | Elastic stack deployed |

---

## Adding a New Tool

```python
# 1. Create file in mcp_server/tools/my_tool.py
def my_tool(param: str) -> dict:
    """Description shown in GUI."""
    return {"status": "ok", "data": ..., "timestamp": ..., "message": ...}

# 2. Restart the API
# Tool auto-appears in GUI CommandPanel — no other changes needed
```

---

## Adding Local Documentation

```bash
# Drop .md files into docs/ or docs/runbooks/
# Then re-run ingestion:
python -m api.memory.ingest

# Docs become searchable in GUI Memory tab
# Agent uses them automatically before acting
```

---

## GUI Tabs

| Tab | What it shows |
|-----|--------------|
| **Commands** | All available tools — click to run |
| **Output** | Live streaming agent output |
| **Status** | Swarm nodes, Kafka brokers, Elastic health |
| **Cluster** | Visual NodeMap of all 6 nodes |
| **Logs** | Audit trail — filter by status, tool, session |
| **Memory** | MuninnDB engrams — search past decisions + docs |
| **Logs (Elastic)** | Live infrastructure logs from Filebeat |

---

## When the Agent Escalates

The agent calls `escalate()` when a decision is high-risk or unfamiliar.
This means:
1. Operation **halts** — nothing irreversible happens
2. Escalation logged to PostgreSQL + MuninnDB
3. GUI shows orange `⚠ escalated` in OutputPanel
4. Alert appears in AlertToast
5. You review → decide whether to proceed manually or via external AI

To send to Claude for a second opinion:
```bash
# Escalation context is pre-packaged — just forward it
# GET /api/logs/escalations → copy context → paste to Claude
```

---

## Checking What the Agent Did

```bash
# Via GUI — Logs tab → filter by session
# Via API
curl http://localhost:8000/api/logs/stats
curl http://localhost:8000/api/logs/operations
curl http://localhost:8000/api/correlate/<operation_id>

# Via DB directly
sqlite3 data/hp1_agent.db "SELECT * FROM tool_calls ORDER BY timestamp DESC LIMIT 20;"
```

---

## Key Files

| File | Purpose |
|------|---------|
| `ROADMAP.md` | Full project reference + all Claude Code prompts |
| `.env` | All configuration — IPs, ports, credentials |
| `.mcp.json` | MCP server wiring for Claude Code |
| `.claude/settings.json` | Claude Code permissions (no prompts) |
| `start.bat` | One-command startup |
| `mcp_server/tools/` | Drop tools here — auto-discovered |
| `docs/runbooks/` | Drop docs here — auto-ingested into MuninnDB |
| `data/hp1_agent.db` | SQLite log DB (or Postgres if DATABASE_URL set) |
| `logs/audit.log` | Raw audit log file |
| `checkpoints/` | State snapshots before risky operations |
