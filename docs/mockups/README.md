# docs/mockups/

Interactive HTML mockups for design spars before CC implementation.

## Convention

- **Path:** `docs/mockups/vX.Y.Z_<short-slug>_round<N>.html` (or `_final.html` after the spar converges)
- **Open:** in a browser — they're self-contained HTML + inline CSS + tiny JS, no build step, no deps
- **Scope:** one file per design decision, not per PR. Multiple rounds in the same spar increment the `_roundN` suffix
- **Disposable-ish:** once CC implements a mockup and it ships, the mockup stays here as design-intent archive. Replaced only when UI is re-thought from scratch

## Not here

- **CC prompts** live in `cc_prompts/` — those are instructions to the executor, not design discussions
- **Design specs** (the words that nail decisions) live as `cc_prompts/SPEC_vX.Y.Z_*.md` next to the matching CC prompt
- **Architecture docs** live at `docs/*.md` (one level up)

## Current mockups

| File | Feature | Status |
|---|---|---|
| `v2.37.0_templates_recent_round1.html` | Templates + Recent section refactor (collapsible, default collapsed) | Spar in progress |
