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
| CC_PROMPT_v2.43.0.md | v2.43.0 | fix(facts+allowlist): swarm service networks in facts + docker service ls allowed | RUNNING |
| CC_PROMPT_v2.43.1.md | v2.43.1 | fix(agents): observe prompt — no-repeat call rule + overlay network vm_exec guidance | PENDING |
