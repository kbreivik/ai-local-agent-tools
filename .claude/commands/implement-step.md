---
description: Execute one implementation step from an active plan, precisely and safely
argument-hint: <plan-filename.md> step <N>
---

## Before starting — read HANDOFF.md
This file contains confirmed node IDs, tool signatures, and current state.
Never rely on memory — always read HANDOFF.md first.

## Step 0 — Identify task
Parse $ARGUMENTS: `<plan-filename> step <N>`
Read `state/plans/<plan-filename>` — find the step, confirm prerequisites are met.
**If previous steps incomplete: STOP and report.**

## Step 1 — Locate (spawn impl-scout)
For EVERY code change, spawn impl-scout first with the specific grep patterns from the plan.
**Do not proceed to Step 2 until impl-scout returns a confirmed FILE:LINE.**

If impl-scout returns "not found": check sibling directories, try alternate patterns,
report what was searched before giving up.

## Step 2 — Downtime impact assessment
Before touching any file, answer:
1. Does this change require container rebuild? (any .py change = yes)
2. What will be unavailable during rebuild? (agent API + GUI, ~3min)
3. Are any dependent services affected? (PostgreSQL/MuninnDB on same VM = no, they survive)
4. Is this step safe to combine with other steps in the same rebuild?

**Hard constraint**: Never change backend + frontend in the same edit session
unless the plan explicitly batches them into one rebuild. One logical change per rebuild.

## Step 3 — Read the target file
Read the exact lines identified by impl-scout (+/- 20 lines context).
Confirm the code matches what the plan expects.
If it doesn't match: stop, report the discrepancy, ask for guidance.

## Step 4 — Implement
Make ONLY the changes specified for this step. Nothing else.

**For agent loop completion fix:**
- Find the exact line after "Agent finished after N steps" is emitted
- Add DB write using the pattern matching the file's existing DB access style
- Wrap in try/except — never let DB failure crash the output stream
- Test import: `python -m py_compile <changed_file>`

**For tool signature fixes:**
- Change function signature in server.py wrapper (not the underlying module)
- Keep the underlying module call unchanged
- Wrap new params in the function body before passing to module
- Test: `python -m py_compile mcp_server/server.py`

**For description-only changes:**
- Update the docstring only
- No behaviour change, no test needed (just syntax check)

## Step 5 — Syntax check (always, before rebuild)
```bash
python -m py_compile <changed_file>
echo "Syntax OK: $?"
# Any error: fix before rebuilding
```

## Step 6 — Rebuild (if required)
```bash
cd /path/to/ai-local-agent-tools
docker build \
  --build-arg DOCKER_GID=$(stat -c '%g' /var/run/docker.sock) \
  -t hp1-ai-agent:latest \
  -f docker/Dockerfile . 2>&1 | tail -30
# If build fails: show error, revert change, STOP

# On success:
cd docker && set -a; source .env; set +a
docker compose up -d
sleep 20
curl -s http://192.168.199.10:8000/api/health | python3 -m json.tool
```

## Step 7 — Verify using plan's verification commands
Run every verification command listed in the plan for this step.
Report PASS / FAIL for each.

**For operations fix — always run this:**
```bash
# 1. Run a simple task
# 2. Wait 15s
# 3. Check:
curl -s "http://192.168.199.10:8000/api/logs/operations?limit=3" | \
  python3 -c "
import sys,json; d=json.load(sys.stdin)
for o in d['operations'][:3]:
  print(f\"{o['status']:10} | {(o.get('completed_at') or 'None')[:19]:20} | {o['label'][:35]}\")
"
```

## Step 8 — Update plan and HANDOFF
Mark the step complete in the plan file.
Update HANDOFF.md with what changed this session.
Run `/handoff` if ending the session.
