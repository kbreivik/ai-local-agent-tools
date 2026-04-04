## Infrastructure
- [ ] Ansible cron jobs auto-recreate when commented out — need ansible variable to toggle (hp1_auto_upgrade: false)
- [ ] Auto-update toggle in GUI not wired up yet — needs background timer + setting persistence
- [ ] DISCOVER_DEFAULT_HOSTS needs more hosts (Proxmox nodes on port 8006, Kibana, Grafana)

## Agent Bugs Found During Testing
- [ ] Agent loop doesn't return final summary after terminal tool calls (audit_log, etc.) — model behavior, may need forced final LLM call
- [ ] audit_log tool schema had dual registration path (server.py vs orchestration.py) — fixed but pattern may affect other tools

## Next Major Work
- [ ] pgvector RAG pipeline for documentation
- [ ] Skill generation for 13+ fingerprinted-but-no-skill platforms
- [ ] Scheduled/proactive analysis (APScheduler or background timer)
- [ ] Plan export format (downloadable runbook for manual execution)
- [ ] Fine-tuning dataset preparation
