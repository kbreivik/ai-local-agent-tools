# CC PROMPT — v2.47.20 — chore: rebuild — v2.47.19 image was a CI flake (279MB instead of 783MB)

## What this does

**No source code changes.** Pure version bump to force CI to rebuild a fresh
Docker image. v2.47.19's CI build (#756) reported Success but produced a
279MB image instead of the expected ~783MB — missing the Python runtime
and most of the app code. Container exits with code 127 ("command not
found") on startup because the entrypoint binary isn't in the image.

The v2.47.19 source code is correct (verified by reading
`api/db/gate_macros.py`, `api/main.py`, `api/routers/tests_api.py`). The
issue is purely a CI/BuildKit flake. Build #756 ran in 31 seconds with
0% cache, which is far too fast for a from-scratch multi-stage build
(npm ci + pip wheel of all deps should take 2-3 minutes).

Forcing a rebuild via VERSION bump is the cleanest recovery. Same source
tree as v2.47.19 ships in a fresh image. After this lands and CI confirms
~783MB, Kent updates docker-compose.yml on agent-01 from `:2.47.18` to
`:2.47.20` and restarts.

Also updates PROJECT_INSTRUCTIONS.md with a CI failure recovery section
so this class of failure has a documented diagnostic and remediation
path.

Version bump: 2.47.19 → 2.47.20

---

## Change 1 — `VERSION` — bump only

CC: open `D:\claude_code\ai-local-agent-tools\VERSION`. The file currently
contains:

```
2.47.19
```

Replace with:

```
2.47.20
```

That's the only change. No newline shenanigans — match the existing format
exactly (single line, trailing newline if the original has one).

---

## Change 2 — `PROJECT_INSTRUCTIONS.md` — add CI failure recovery section

CC: open `D:\claude_code\ai-local-agent-tools\PROJECT_INSTRUCTIONS.md`.
Find the section heading "## Hard-Won Operational Patterns". After the
"### Diagnostic data sources" subsection (and before "### Communication
style with the user"), insert this new subsection:

```markdown
### CI build failure — broken `:latest` image recovery
**Symptom**: Container restart-loops with exit code 127 (command not found).
GUI unreachable. `docker logs hp1_agent` shows entrypoint binary missing.

**Diagnosis** (single command):
```bash
sudo docker images | grep hp1-ai-agent
```

If `:latest` image size is significantly smaller than tagged versions
(e.g. 279MB vs 783MB), the CI build pushed a partial/broken artifact
even though the Actions run reported "Success". GHCR may have the same
broken image; pulling fresh won't help.

**Recovery** (60 seconds):
```bash
cd /opt/hp1-agent/docker
sudo cp docker-compose.yml docker-compose.yml.bak
# Pin to last-known-good tagged version (check sizes via docker images)
sudo sed -i 's|hp1-ai-agent:latest|hp1-ai-agent:<good-version>|' docker-compose.yml
sudo docker compose --env-file .env up -d hp1_agent
sleep 10
curl -s http://localhost:8000/api/health | jq .version
```

**Permanent fix**: bump VERSION (no code changes needed) and push to
trigger a fresh CI build. The new build typically succeeds. Once it
completes and GHCR shows the expected size, pin compose to the new
explicit version.

**Going forward**: prefer pinning compose to explicit `:X.Y.Z` over
`:latest`. The `:latest` tag offers no protection against this class of
failure. Each successful CC deploy can update the pin as part of its
verification step.

**Lesson learned**: Don't trust `:latest` blindly. Image listing on
agent-01 (`docker images`) is the source of truth for what versions
actually pulled cleanly. CI "Success" means the steps ran without
error — it does not guarantee a complete artifact was published.
```

CC: keep the existing section heading hierarchy (`###` for the new
subsection, parallel to the others under "Hard-Won Operational
Patterns"). Match the existing markdown style — no extra blank lines
between sub-sections beyond what the others use.

---

## Verify

```bash
# 1. VERSION updated
cat VERSION
# Expected: 2.47.20

# 2. Project instructions updated
grep -c "CI build failure" PROJECT_INSTRUCTIONS.md
# Expected: at least 1

# 3. No source code changed
git diff --name-only HEAD~1
# Expected: VERSION, PROJECT_INSTRUCTIONS.md, cc_prompts/CC_PROMPT_v2.47.20.md, cc_prompts/INDEX.md
# (NOT api/* or gui/*)
```

After CI finishes building v2.47.20:

```bash
# Manually confirm the new image is full-size on GHCR before pinning
ssh agent-01
sudo docker pull ghcr.io/kbreivik/hp1-ai-agent:2.47.20
sudo docker images | grep 2.47.20
# Expected size: ~783MB. If smaller, REPEAT the version bump (v2.47.21)
# until CI produces a clean image.
```

If size is correct:

```bash
cd /opt/hp1-agent/docker
sudo sed -i 's|hp1-ai-agent:2.47.18|hp1-ai-agent:2.47.20|' docker-compose.yml
sudo docker compose --env-file .env up -d hp1_agent
sleep 10
curl -s http://localhost:8000/api/health | jq .version
# Expected: "2.47.20"

# Then validate gate_macros endpoints actually work
TOKEN=$(...)
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/tests/macros | jq
# Expected: {"macros": []}
```

---

## What this does NOT do

- **No source code changes.** v2.47.19's source is correct as-is.
- **Does not modify `docker/docker-compose.yml` in the repo.** The
  deployed compose at `/opt/hp1-agent/docker/docker-compose.yml` on
  agent-01 is maintained separately. Operator pins manually.
- **Does not investigate WHY CI produced a 279MB image.** That's a
  one-off forensic question (BuildKit cache corruption? registry blob
  truncation? layer push race?). The pragmatic fix is to rebuild and
  move on. If it happens again on v2.47.20 build, escalate to investigating
  build.yml + Dockerfile + GHCR retention settings.
- **Does not pin compose to explicit version in the repo.** Worth doing
  but separate concern — queue as v2.47.21+ if the operator wants this
  hardened.

---

## Version bump

Update `VERSION`: `2.47.19` → `2.47.20`

---

## Commit

```bash
git add -A
git commit -m "chore: v2.47.20 force CI rebuild (v2.47.19 image was 279MB instead of 783MB)"
git push origin main
```

Deploy: see Verify section above. CI builds the image; operator pins
docker-compose.yml on agent-01 manually after confirming GHCR size.
