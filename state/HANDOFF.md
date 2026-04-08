# HANDOFF — 2026-04-08T16:00:00Z

## Git state
Branch: main
Latest: 3c6f842 — fix(connections): platform-targeted collector repoll
VERSION: 1.22.6
186 tests pass

## What was built this session

### Multi-user auth + API tokens (v1.22.0)
- api/users.py: users + api_tokens Postgres tables, bcrypt, SHA256 token hash
- api/routers/users.py: 7 endpoints (CRUD users + tokens)
- api/auth.py: authenticate() checks users table → env fallback; decode_token() tries JWT → API token
- Frontend AccessTab: USERS sub-tab (table + add + role dropdown + enable/disable + delete) + API TOKENS sub-tab (generate + revoke + raw token display)
- Roles: sith_lord, imperial_officer, stormtrooper, droid

### Connections as universal service registry (v1.21.0)
- External services collector rewritten — connections-driven, 20 platform health checks
- Proxmox skill accepts connection_id parameter
- Alert system enriched with connection_label + connection_id
- Platform-targeted collector repoll on create/update/delete

### V3a Imperial Ops theme (v1.20.2+)
- Star Wars theme: Share Tech Mono + Rajdhani fonts, crimson accent, 2px sharp corners
- DS orb sidebar with collapse, settings sub-nav (8 items)
- Drill-down bar: search + SHOW/TYPE filters + GLOBAL MAINT button + stats
- Section accordion dashboard: PLATFORM / COMPUTE / CONTAINERS / NETWORK / STORAGE / SECURITY
- Dynamic connection cards in NETWORK/STORAGE/SECURITY sections

### Settings page (v1.20.0+)
- Full page (not modal) with 8 tabs
- Naming tab with live preview
- Permissions tab with role matrix
- Access tab with user + token management
- Connections tab with per-platform credential fields
- Infrastructure moved service connections to Connections tab

### Other fixes
- Proxmox collector: proxmoxer library, auto-discover nodes, user/token_name/secret fields
- Network SSH collector (netmiko) for FortiSwitch/Cisco/Juniper
- Logs tab: connection source filter pills with cyan border
- JWT: hostname-derived deterministic fallback (survives restarts)
- Agent loop: last_reasoning in done broadcast
- Tool registry: unified build_tools_spec()

## Architecture summary
- 26 platform tools (plugins + skills)
- 7 collectors: swarm, kafka, elastic, proxmox_vms, docker_agent01, external_services, network_ssh
- Connections DB: universal service registry (Postgres + SQLite fallback)
- pgvector RAG: 607 chunks, hybrid search, tiered agent injection
- ONNX Runtime embeddings (bge-small-en-v1.5, no PyTorch)
- Plugin architecture: 3-tier (core → plugin → skill)
- Settings encryption: Fernet for secrets at rest

## Active issues
- test_routers_dashboard.py: 2 pre-existing failures (httpx mock mismatch)
- Container needs rebuild for latest code
- ADMIN_PASSWORD=changeme in production .env

## Next actions
- Rebuild + deploy v1.22.6
- Test multi-user auth end-to-end
- Wire Naming tab values to sidebar branding (DS orb text, footer agent name)
