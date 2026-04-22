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
| CC_PROMPT_v2.40.4.md | v2.40.4 | refactor(agents): extract context-building helpers into api/agents/context.py | RUNNING |
| CC_PROMPT_v2.41.0.md | v2.41.0 | refactor(agents): StepState dataclass — consolidate _run_single_agent_step accumulators | PENDING |
| CC_PROMPT_v2.41.1.md | v2.41.1 | refactor(agents): extract step_llm.py — LLM call, trace, working memory | PENDING |
| CC_PROMPT_v2.41.2.md | v2.41.2 | refactor(agents): extract step_guard.py — hallucination guard + fabrication detector | PENDING |
| CC_PROMPT_v2.41.3.md | v2.41.3 | refactor(agents): extract step_facts.py — fact extraction, contradiction, zero-pivot, diagnostics | PENDING |
| CC_PROMPT_v2.41.4.md | v2.41.4 | refactor(agents): step_synth.py + to_result_dict — complete split phase 1 | PENDING |
| CC_PROMPT_v2.41.5.md | v2.41.5 | refactor(agents): extract step_tools.py — full tool dispatch loop | PENDING |
