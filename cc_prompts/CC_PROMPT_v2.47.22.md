# CC PROMPT — v2.47.22 — fix(docker): pin transformers<5.0 + --no-deps runtime install (root cause of v2.47.19/20/21 broken builds)

## What this does

Root cause confirmed via v2.47.21's now-loud build failure. CI log
shows:

```
#22 2.017 transformers 5.6.2 depends on tokenizers<=0.23.0 and >=0.22.0
#22 2.017 Additionally, some packages in these conflicts have no matchi...
```

Timeline:
- HuggingFace shipped `transformers 5.6.2` to PyPI recently with a
  tighter `tokenizers<=0.23.0` upper bound.
- `tokenizers 0.23.1` was also just released.
- requirements.txt has `tokenizers>=0.15.0` (no upper bound) and
  Dockerfile pulls `transformers` (latest, no pin).
- Builder stage: `pip wheel -r requirements.txt` picks tokenizers
  0.23.1; `pip wheel transformers --no-deps` picks transformers 5.6.2.
- Runtime stage: `pip install /wheels/*.whl` runs full resolver, sees
  conflict (5.6.2 wants <=0.23.0, we have 0.23.1), fails.

v2.47.18 built ~5 hours before transformers 5.6.2 hit PyPI — pure
timing, nothing about the v2.47.19 source change caused this. v2.47.19
and v2.47.20 silently shipped 279MB images because of v2.47.21's now-
fixed `|| true` mask. v2.47.21 itself failed loudly (correctly) once
the mask was removed.

Fix: two layers, both in the Dockerfile.

1. **`--no-deps` on the runtime `pip install`.** The builder stage
   already resolved deps via `pip wheel -r requirements.txt`. The
   wheels in /wheels ARE the resolved set. Re-running the resolver at
   runtime install adds nothing but conflict surface. `--no-deps`
   tells pip "trust me, install these wheels, don't re-check."

2. **Pin transformers to `<5.0` in the builder stage.** The platform
   uses transformers only for its tokenizer integration (per the
   existing comment: "Only tokenizers, numpy, huggingface-hub,
   safetensors are needed at runtime"). The 4.x line has compatible
   tokenizers pinning. Pinning to <5.0 explicitly avoids future
   re-occurrence when HuggingFace tightens 5.x more.

After this lands, build duration goes back to ~2-3 minutes (no-cache:
true is still on from v2.47.21), produces a ~783MB image, and pip
install no longer re-resolves at runtime.

Version bump: 2.47.21 → 2.47.22

---

## Change 1 — `docker/Dockerfile` — pin transformers + add --no-deps at runtime

CC: open `docker/Dockerfile`. Two edits:

### 1a. Pin transformers in the builder stage

Find:

```dockerfile
COPY requirements.txt .
# Install transformers without deps to prevent PyTorch from being pulled in.
# Only tokenizers, numpy, huggingface-hub, safetensors are needed at runtime.
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt && \
    pip wheel --no-cache-dir --wheel-dir /wheels transformers --no-deps
```

Replace with:

```dockerfile
COPY requirements.txt .
# Install transformers without deps to prevent PyTorch from being pulled in.
# Only tokenizers, numpy, huggingface-hub, safetensors are needed at runtime.
# v2.47.22: pin to <5.0 — transformers 5.6.2 (released 2026-04) tightened
# its tokenizers upper bound to <=0.23.0, conflicting with the latest
# tokenizers 0.23.1 that pip resolves from requirements.txt. The 4.x line
# has compatible pinning and is sufficient for our tokenizer-only usage.
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt && \
    pip wheel --no-cache-dir --wheel-dir /wheels "transformers<5.0" --no-deps
```

### 1b. Add `--no-deps` to the runtime install

Find (in the runtime stage, edited in v2.47.21):

```dockerfile
# Install Python wheels from builder (all deps, no pip at runtime)
COPY --from=builder /wheels /wheels
# v2.47.21 — split previous chain. The old line had `|| true` at the end
# to handle the torch-absent case, but shell short-circuit semantics
# meant `|| true` ALSO swallowed pip install failures — building broken
# images that report "Success". v2.47.19 and v2.47.20 hit this exact
# trap (8MB installed instead of 512MB; pip silently failed partway).
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels
# Sanity-check: torch must NOT have been pulled in. The negation
# inverts the condition cleanly without short-circuit pitfalls.
RUN if python -c "import torch" 2>/dev/null; then \
        echo "ERROR: torch installed unexpectedly — check requirements.txt" && exit 1; \
    fi
```

Replace with:

```dockerfile
# Install Python wheels from builder (all deps, no pip at runtime)
COPY --from=builder /wheels /wheels
# v2.47.21 — split previous chain. The old line had `|| true` at the end
# to handle the torch-absent case, but shell short-circuit semantics
# meant `|| true` ALSO swallowed pip install failures — building broken
# images that report "Success". v2.47.19 and v2.47.20 hit this exact
# trap (8MB installed instead of 512MB; pip silently failed partway).
# v2.47.22 — added --no-deps. The builder stage already resolved deps
# via `pip wheel -r requirements.txt`; /wheels IS the resolved set.
# Re-running the resolver at runtime install adds nothing except
# conflict surface (e.g. transformers 5.6.2 + tokenizers 0.23.1 from
# v2.47.21's failure). --no-deps tells pip to install the listed wheels
# without re-resolving — exactly what we want.
RUN pip install --no-cache-dir --no-deps /wheels/*.whl && rm -rf /wheels
# Sanity-check: torch must NOT have been pulled in. The negation
# inverts the condition cleanly without short-circuit pitfalls.
RUN if python -c "import torch" 2>/dev/null; then \
        echo "ERROR: torch installed unexpectedly — check requirements.txt" && exit 1; \
    fi
```

CC: this is two minimal edits. The first adds `<5.0` to the
transformers pin in the builder stage. The second adds `--no-deps`
flag and a comment block to the runtime install. Don't touch any other
RUN / COPY lines.

---

## Change 2 — `VERSION` — bump

CC: open `D:\claude_code\ai-local-agent-tools\VERSION`. Replace
`2.47.21` with `2.47.22`.

---

## Change 3 — `PROJECT_INSTRUCTIONS.md` — add transient PyPI dependency conflicts to operational patterns

CC: open `PROJECT_INSTRUCTIONS.md`. Find the "### CI build failure —
broken `:latest` image recovery" section (added in v2.47.20). After
the closing of that section but BEFORE the "### Communication style
with the user" subsection, add this new subsection:

```markdown
### Transient PyPI dependency conflicts in Docker builds
**Symptom**: A previously-working Docker build suddenly fails (or in
older Dockerfiles, silently produces a tiny image) with pip resolution
errors. Often happens when a major dependency (transformers, pydantic,
sqlalchemy) ships a new version with tighter pins.

**Root cause**: requirements.txt without upper-bound pins allows pip
to pick the latest version of every dep. When an upstream package
ships a new release with stricter constraints (e.g. transformers 5.6.2
adding `tokenizers<=0.23.0`), the resolver fails because we already
have a newer version (e.g. 0.23.1) selected from requirements.txt's
floor-only pin.

**Diagnosis**: search the failed pip install log for `looking at
multiple versions` or `depends on X<=Y`. The package right before that
line is the conflicting dep.

**Fix patterns** (in order of preference):
1. **Add `--no-deps` to the runtime `pip install`** — the builder
   stage already resolved deps via `pip wheel -r requirements.txt`.
   Re-running the resolver at runtime install adds no value, only
   conflict surface. This is the standard pattern in the repo since
   v2.47.22.
2. **Pin the offending package to a major version** in the Dockerfile
   (e.g. `transformers<5.0`) — surgical and explicit.
3. **Pin in requirements.txt** with both lower and upper bounds — only
   if multiple Dockerfile-side pins would compound.

**Why this is sneaky in CI**: PyPI is mutable. The same source code +
same Dockerfile can produce different builds on different days because
upstream packages publish new versions between runs. Without `--no-deps`
in the runtime install, this class of failure can recur any time a
deeply-pinned dependency releases a tighter version.
```

CC: keep markdown style consistent with surrounding subsections.

---

## Verify

```bash
# 1. Pin landed
grep "transformers<5.0" docker/Dockerfile
# Expected: 1 match in the builder stage

# 2. --no-deps landed
grep "pip install --no-cache-dir --no-deps" docker/Dockerfile
# Expected: 1 match in the runtime stage

# 3. VERSION
cat VERSION
# Expected: 2.47.22

# 4. Project instructions section
grep "Transient PyPI dependency conflicts" PROJECT_INSTRUCTIONS.md
# Expected: 1 match
```

After CI completes (~2-3 min with no-cache):

```bash
ssh agent-01
sudo docker pull ghcr.io/kbreivik/hp1-ai-agent:2.47.22
sudo docker images | grep 2.47.22
# Expected: ~783MB

# Spot-check pip install layer size
sudo docker history ghcr.io/kbreivik/hp1-ai-agent:2.47.22 --no-trunc | grep "pip install"
# Expected: ~510MB layer (matches v2.47.18's 512MB)

# If size is correct:
cd /opt/hp1-agent/docker
sudo sed -i 's|hp1-ai-agent:2.47.18|hp1-ai-agent:2.47.22|' docker-compose.yml
sudo docker compose --env-file .env up -d hp1_agent
sleep 10
curl -s http://localhost:8000/api/health | jq .version
# Expected: "2.47.22"

# Validate gate_macros endpoints (the whole point of v2.47.19's source change)
TOKEN=$(...)
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/tests/macros | jq
# Expected: {"macros": []}
```

---

## What this does NOT do

- **Does not pin every dep with upper bounds.** That's a maintenance
  burden best avoided. `--no-deps` at install time is the correct
  long-term answer.
- **Does not remove the no-cache flag** added in v2.47.21. Keep it on
  — bypass any potential cache contamination.
- **Does not investigate whether transformers 4.x has its own future
  conflicts.** If/when this recurs, repeat the diagnostic flow:
  search log for "depends on", pin or refactor.

---

## Version bump

Update `VERSION`: `2.47.21` → `2.47.22`

---

## Commit

```bash
git add -A
git commit -m "fix(docker): v2.47.22 pin transformers<5.0 + --no-deps runtime install"
git push origin main
```
