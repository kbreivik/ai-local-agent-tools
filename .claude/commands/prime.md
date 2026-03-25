---
description: Load focused context for this session
---

Read `state/HANDOFF.md` if it exists — this anchors the session.

Then spawn **service-scout** to gather:
1. `curl -s http://192.168.199.10:8000/api/health` — agent version and deploy mode
2. `curl -s http://192.168.199.10:8000/api/skills` — skill count and categories
3. `git log --oneline -5` — recent changes
4. List state/plans/*.md — any active plans?

Summarise in ≤200 words:
- Agent version, build number, running status
- How many skills are registered (by category)
- Most recent code changes
- Active task from HANDOFF.md
- Next action

Do NOT load full skill module files unless specifically needed.
Do NOT load logs or memory dumps.
