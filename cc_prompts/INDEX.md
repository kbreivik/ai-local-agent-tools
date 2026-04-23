# DEATHSTAR CC Prompt Queue

```bash
cd /d/claude_code/ai-local-agent-tools
bash cc_prompts/run_queue.sh --dry-run
bash cc_prompts/run_queue.sh --one
bash cc_prompts/run_queue.sh
```

## Queue

| File | Version | Description | Status |
|---|---|---|---|
| CC_PROMPT_v2.40.4.md | v2.40.4 | refactor(agents): extract context-building helpers into api/agents/context.py | DONE (f030da3) |
| CC_PROMPT_v2.41.0.md | v2.41.0 | refactor(agents): StepState dataclass — consolidate _run_single_agent_step accumulators | DONE (91cd2a9) |
| CC_PROMPT_v2.41.1.md | v2.41.1 | refactor(agents): extract step_llm.py — LLM call, trace, working memory | DONE (f0e5302) |
| CC_PROMPT_v2.41.2.md | v2.41.2 | refactor(agents): extract step_guard.py — hallucination guard + fabrication detector | DONE (3fb8033) |
| CC_PROMPT_v2.41.3.md | v2.41.3 | refactor(agents): extract step_facts.py — fact extraction, contradiction, zero-pivot, diagnostics | DONE (d19fc46) |
| CC_PROMPT_v2.41.4.md | v2.41.4 | refactor(agents): step_synth.py + to_result_dict — complete split phase 1 | DONE (0eca936) |
| CC_PROMPT_v2.41.5.md | v2.41.5 | refactor(agents): extract step_tools.py — full tool dispatch loop | DONE (2def784) |
| CC_PROMPT_v2.42.0.md | v2.42.0 | test(agents): test_gates.py — pure gate function coverage | DONE (6383675) |
| CC_PROMPT_v2.42.1.md | v2.42.1 | test(agents): test_step_state.py — StepState dataclass contract tests | DONE (6c8c741) |
| CC_PROMPT_v2.42.2.md | v2.42.2 | test(agents): test_step_guard_facts.py — mock-based guard + fact extraction tests | DONE (96dce13) |
| CC_PROMPT_v2.42.3.md | v2.42.3 | feat(memory): MuninnDB first-tool hints — step 0 suggestion from historical sequences | DONE (5cec4c0) |
| CC_PROMPT_v2.43.0.md | v2.43.0 | fix(facts+allowlist): swarm service networks in facts + docker service ls allowed | DONE (1b6939a) |
| CC_PROMPT_v2.43.1.md | v2.43.1 | fix(agents): observe prompt — no-repeat call rule + overlay network vm_exec guidance | DONE (b0f3fbe) |
| CC_PROMPT_v2.43.2.md | v2.43.2 | fix(facts): resolve swarm overlay network IDs to human-readable names in collector + extractor | DONE (3e86980) |
| CC_PROMPT_v2.43.3.md | v2.43.3 | fix(facts): swarm node addr_anomaly flag + preflight keyword resolver for split-brain detection | DONE (880c6bd) |
| CC_PROMPT_v2.43.4.md | v2.43.4 | fix(facts): write prod.swarm.cluster.overlay_networks from collector net_id_to_name map | DONE (1019023) |
| CC_PROMPT_v2.43.5.md | v2.43.5 | fix(facts+agents): swarm hostname↔connection_label cross-ref facts + entity name mapping prompt section | DONE (1f37cfc) |
| CC_PROMPT_v2.43.6.md | v2.43.6 | feat(ui): Collectors monitor view + Session Output sidebar items | DONE (552829e) |
| CC_PROMPT_v2.43.7.md | v2.43.7 | feat(ui): Facts & Knowledge card on dashboard under Platform Core section | DONE (3c50378) |
| CC_PROMPT_v2.43.8.md | v2.43.8 | feat(settings): memoryEnabled toggle — NullMuninnClient when disabled | DONE (0b110aa) |
| CC_PROMPT_v2.43.9.md | v2.43.9 | feat(memory): pg_engrams table + PgMemoryClient — PG-native memory backend | DONE (d3ea11f) |
| CC_PROMPT_v2.44.0.md | v2.44.0 | fix(settings): add memoryEnabled + memoryBackend to SETTINGS_KEYS | DONE (e67bf49) |
| CC_PROMPT_v2.44.1.md | v2.44.1 | feat(tests): DB-backed test run history — test_runs + suites + schedules + compare API | DONE (41578fe) |
| CC_PROMPT_v2.44.2.md | v2.44.2 | feat(ui): TestsPanel complete overhaul — Library, Suites, Compare, Trend, Schedule | DONE (d9589e3) |
| CC_PROMPT_v2.44.3.md | v2.44.3 | fix(tests): add tests/__init__.py files so API can import TEST_CASES | DONE (d9589e3) |
| CC_PROMPT_v2.44.4.md | v2.44.4 | fix(docker): narrow .dockerignore — include tests/integration/ in container image | DONE (19052a2) |
| CC_PROMPT_v2.44.5.md | v2.44.5 | fix(tests): move TestCase+TEST_CASES to api/db/test_definitions.py — always in container | DONE (f7259b3) |
| CC_PROMPT_v2.44.6.md | v2.44.6 | fix(tests): correct get_test_cases field names (timeout_s, expect_tools, agent_type) | DONE (b6f1ef4) |
| CC_PROMPT_v2.44.7.md | v2.44.7 | fix(tests): wire suite_id+test_ids through run — apply suite config + fix http client | DONE (e48a3db) |
| CC_PROMPT_v2.44.8.md | v2.44.8 | feat(ui): AnalysisView — grouped dropdown, search, date quick-selects, table view, history sidebar | RUNNING |
