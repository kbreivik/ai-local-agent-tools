# DEATHSTAR CC Prompt Queue

Agreed improvement phases from architecture review on 2026-04-12.
Run in version order. Each file is a standalone CC prompt.

Earlier prompts (v2.6.x–v2.7.x) are in the project root as `CC_PROMPT_vX.X.X.md`.

---

## Automated Queue Runner

The queue can run itself. CC reads the index, implements each PENDING prompt in order,
commits and pushes to git, marks it DONE, then moves to the next automatically.

```bash
# Run all pending prompts end-to-end (unattended)
bash cc_prompts/run_queue.sh

# See what's pending without executing
bash cc_prompts/run_queue.sh --dry-run

# Run just the next one (useful for supervised execution)
bash cc_prompts/run_queue.sh --one
```

Or invoke CC directly for a single supervised run:
```bash
claude "$(cat cc_prompts/QUEUE_RUNNER.md)"
```

The runner uses `--dangerously-skip-permissions` so CC edits files and runs git without
prompting each action. Remove that flag from `run_queue.sh` if you want interactive approval.

---

## Phase Queue

| File | Version | Theme | Status |
|---|---|---|---|
| CC_PROMPT_v2.8.0.md | v2.8.0 | AI loop: semantic tool routing + thinking memory + feedback pre-ranking | PENDING |
| CC_PROMPT_v2.8.1.md | v2.8.1 | LLM temperature profile + /no_think for cheap steps | PENDING |
| CC_PROMPT_v2.9.0.md | v2.9.0 | Entity state DB: change tracking + event log + image digest | PENDING |
| CC_PROMPT_v2.9.1.md | v2.9.1 | Entity history agent tools + context injection + GUI badge | PENDING |
| CC_PROMPT_v2.10.0.md | v2.10.0 | Lightweight coordinator pattern between agent steps | PENDING |

---

## Version bump rationale

| Version | Change type |
|---|---|
| x.x.1 | Targeted fix, tuning, or small addition |
| x.1.x | New subsystem, architectural change, or multi-file feature |

v2.8.0 — significant AI loop quality change (semantic routing affects every step)
v2.8.1 — targeted tuning on top of 2.8.0
v2.9.0 — new persistent DB layer (new tables, collector instrumentation)
v2.9.1 — tooling + GUI on the 2.9.0 DB layer
v2.10.0 — major architectural change to agent loop (coordinator pattern)

---

## What each phase delivers

**v2.8.0** — Embeds tool descriptions using the ONNX model already loaded for RAG,
ranks by cosine similarity to the task, sends only top-10 relevant tools per step.
Extracts key facts from `<think>` blocks as compact working memory for the next step.
Boosts historically successful tools to the front of the manifest.

**v2.8.1** — Force-summary calls get temperature 0.3 for better prose.
`/no_think` injected for audit_log-only steps. `min_p=0.1` for consistent JSON args.

**v2.9.0** — Two new permanent tables: entity_changes (field-level diffs) and entity_events
(discrete named events). Collectors detect changes between polls. Image digest tracking
catches silent re-deploys ("same tag, new image under the hood").

**v2.9.1** — `entity_history()` and `entity_events()` tools for the agent.
Automatic injection: recent changes/events prepended to system prompt when task mentions
a known entity. GUI entity card badges show change/event counts with severity colouring.

**v2.10.0** — Adaptive coordinator: tiny LLM call (no tools, 200 tokens, /no_think)
after each step decides done/continue/query/escalate. Dynamic step extension at runtime.
Structured JSON context between steps replaces prose summaries.

---

## Key file paths for CC context

```
api/routers/agent.py         — agent loop, safety gates, _summarize_tool_result
api/agents/router.py         — classifier, domain detector, tool allowlists, prompts
api/agents/orchestrator.py   — step planner, verdict extraction, coordinator (v2.10+)
api/memory/hooks.py          — MuninnDB before/after_tool_call hooks
api/memory/feedback.py       — outcome recording, past_outcomes retrieval
api/rag/doc_search.py        — pgvector hybrid search (bge-small-en-v1.5 ONNX)
api/db/entity_history.py     — entity_changes + entity_events tables (v2.9.0+)
api/db/result_store.py       — large result storage + temp table queries
api/db/ssh_log.py            — SSH attempt log
api/db/ssh_capabilities.py   — credential→host capability map
api/db/infra_inventory.py    — hostname/IP SOT
mcp_server/tools/vm.py       — vm_exec, infra_lookup, ssh_capabilities
mcp_server/tools/docker_api.py  — docker_df, docker_prune, docker_images
mcp_server/tools/result_tools.py — result_fetch, result_query
plugins/unifi_network_status.py  — UniFi plugin (DB-first credentials)
api/collectors/vm_hosts.py   — SSH polling, _ssh_run, change detection (v2.9.0+)
api/collectors/swarm.py      — Docker SDK swarm polling, image digest tracking
gui/src/components/          — React frontend components
```

## Stack

- FastAPI + Python backend
- React + Vite frontend  
- Postgres (pgvector/pg16) at 127.0.0.1:5433
- MuninnDB (Hebbian memory) at ghcr.io/scrypster/muninndb
- LM Studio (Qwen3-coder-next) at env LM_STUDIO_BASE_URL
- Docker Compose deploy on Linux 192.168.199.10:8000
- Repo: https://github.com/kbreivik/ai-local-agent-tools
