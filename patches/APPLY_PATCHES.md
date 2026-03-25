# Implementation Guide — Apply Both Patches
# One Claude Code session, one container rebuild, zero guessing.
#
# Prerequisites:
#   - Claude Code open in ai-local-agent-tools repo root
#   - /prime run (reads HANDOFF.md)
#   - Agent running on 192.168.199.10:8000
#
# ─────────────────────────────────────────────────────────────────────────────
# SESSION WORKFLOW
# ─────────────────────────────────────────────────────────────────────────────

# 1. Read HANDOFF
/prime

# 2. Confirm source locations (takes 30 seconds)
grep -n "await logger_mod.complete_operation" api/routers/agent.py
# Expected: line ~815
grep -n "def stop_agent" api/routers/agent.py
# Expected: line ~872
grep -n "def audit_log" mcp_server/server.py
# Expected: line ~144
grep -n "def discover_environment" mcp_server/server.py
# Expected: line ~440
grep -n "def skill_execute" mcp_server/server.py
# Expected: line ~450
grep -n "def node_activate" mcp_server/server.py
grep -n "def node_drain" mcp_server/server.py

# 3. Apply agent.py changes
#    Edit api/routers/agent.py — two changes from patch_agent_router.txt
#    Change 1: add flush_now() before complete_operation (line ~814)
#    Change 2: replace stop_agent body to add DB update (line ~872)

python -m py_compile api/routers/agent.py && echo "agent.py OK"

# 4. Apply server.py changes
#    Edit mcp_server/server.py — four changes from patch_server_py.txt
#    Change 1: audit_log — add target, details params
#    Change 2: discover_environment — add default hosts + hosts_json alias
#    Change 3: skill_execute — update description (no param change)
#    Change 4: node_activate/node_drain — update descriptions with hex IDs

python -m py_compile mcp_server/server.py && echo "server.py OK"

# 5. Build
docker build \
  --build-arg DOCKER_GID=$(stat -c '%g' /var/run/docker.sock) \
  -t hp1-ai-agent:latest \
  -f docker/Dockerfile . 2>&1 | tail -20
# Expected: Successfully built <id>

# 6. Deploy
cd docker && set -a; source .env; set +a
docker compose up -d
sleep 20
curl -s http://192.168.199.10:8000/api/health | python3 -m json.tool

# 7. Verify — run a test task
curl -s -X POST http://192.168.199.10:8000/api/agent/run \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(cat /tmp/hp1_token 2>/dev/null || echo TOKEN)" \
  -d '{"task":"Run swarm_status and report node count. Then run audit_log with action=test result=ok target=swarm-verify. Keep response to 20 words."}'
# Get the operation_id from response

# Wait 15s, then check:
sleep 15
curl -s "http://192.168.199.10:8000/api/logs/operations?limit=3" | \
  python3 -c "
import sys,json; d=json.load(sys.stdin)
for o in d['operations'][:3]:
  print(f\"{o['status']:12} | {(o.get('completed_at') or 'None')[:19]:20} | {o['label'][:40]}\")
"
# Expected: 'completed    | 2026-03-24T...        | Run swarm_status...'

curl -s "http://192.168.199.10:8000/api/logs/stats" | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print('success_rate:', d['success_rate'], '%')"
# Expected: success_rate > 0

# 8. Clean up stuck operations (after confirming rebuild works)
docker exec hp1-agent python3 << 'PYEOF'
import asyncio, sys
sys.path.insert(0, '/app')

async def cleanup():
    from api.db.base import get_engine
    from api.db import queries as q
    from sqlalchemy import text
    async with get_engine().begin() as conn:
        result = await conn.execute(
            text("SELECT COUNT(*) FROM operations WHERE status='running'")
        )
        count = result.scalar()
        print(f"Stuck operations: {count}")
        if count > 0:
            await conn.execute(
                text("UPDATE operations SET status='stopped', completed_at=datetime('now') WHERE status='running'")
            )
            print(f"Cleaned up {count} operations")

asyncio.run(cleanup())
PYEOF
# Expected: "Stuck operations: 14" then "Cleaned up 14 operations"

# 9. Verify clean state
curl -s "http://192.168.199.10:8000/api/logs/stats" | python3 -m json.tool

# 10. Commit
/commit
# Message: "fix(agent): flush write queue before operation completion + stop handler DB update
#
# Operations never showed 'completed' because logger uses async batch writes (100ms
# flush interval). Background task exited before queue flushed.
# Fix: await logger_mod.flush_now() before complete_operation call.
#
# stop_agent also now marks operation as stopped in DB instead of only setting
# in-memory cancel flag.
#
# Co-fix: mcp_server/server.py — audit_log accepts target/details params,
# discover_environment defaults to HP1 hosts, node descriptions embed hex node IDs."

# ─────────────────────────────────────────────────────────────────────────────
# EXPECTED OUTCOMES AFTER THIS SESSION
# ─────────────────────────────────────────────────────────────────────────────
# - Operations show status='completed' after every task finish
# - success_rate > 0% (operations correctly counted)
# - audit_log(action, result, target=...) no longer errors
# - discover_environment() with no args scans HP1 hosts automatically
# - node_activate/drain descriptions contain hex IDs — no more hostname mistakes
# - 14 stuck operations cleaned up → zero 'running' in DB
