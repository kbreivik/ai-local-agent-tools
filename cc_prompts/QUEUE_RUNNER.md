# DEATHSTAR Prompt Queue Runner — Single-prompt instruction

You are implementing ONE specific prompt for the DEATHSTAR project.
The prompt file and version are specified below by the calling script.

DO NOT loop to the next prompt. Implement ONLY the prompt provided.
The bash script (run_queue.sh) controls iteration — your job is one prompt.

---

## Your task for this invocation

### Step 1 — Understand the prompt

Read the prompt content carefully. It specifies:
- Exact files to create or modify
- Exact functions to add or change
- A version number to write to VERSION file
- A git commit message to use

### Step 2 — Read existing files before editing

Before changing any file, read its current content so you understand
the existing structure. Use exact function names and file paths from the prompt.
Never rewrite a whole file when the prompt says to add or update a section.

### Step 3 — Implement all changes

Make every change described in the prompt. If the prompt says NEW FILE, create it.
If it says "add after X" or "replace Y with Z", do exactly that.
Update the VERSION file to the version number in the prompt header.

### Step 4 — Verify

Run syntax checks on changed Python files:
```bash
cd D:\claude_code\ai-local-agent-tools
python -m py_compile <any changed .py files>
```

If py_compile fails, fix the error before committing.

### Step 5 — Commit and push

Use the exact commit message from the prompt's ## Commit section.

```bash
git add -A
git commit -m "<message from prompt>"
git push origin main
```

Verify push succeeded:
```bash
git log --oneline -1
```

### Step 5.5 — Build and push Docker image

After the git push succeeds, build and push the container image. Tag with
both `:latest` and the version string from the VERSION file, so every
release is addressable by tag going forward.

```bash
cd D:\claude_code\ai-local-agent-tools
VER=$(cat VERSION | tr -d '[:space:]')
SHORT=$(git rev-parse --short HEAD)

# Build (single-arch, linux/amd64 — matches agent-01). Adjust if needed.
docker build \
  --build-arg BUILD_COMMIT=$(git rev-parse HEAD) \
  --build-arg BUILD_BRANCH=$(git branch --show-current) \
  --build-arg BUILD_NUMBER=local \
  -t ghcr.io/kbreivik/hp1-ai-agent:latest \
  -t ghcr.io/kbreivik/hp1-ai-agent:${VER} \
  -t ghcr.io/kbreivik/hp1-ai-agent:sha-${SHORT} \
  .

docker push ghcr.io/kbreivik/hp1-ai-agent:latest
docker push ghcr.io/kbreivik/hp1-ai-agent:${VER}
docker push ghcr.io/kbreivik/hp1-ai-agent:sha-${SHORT}
```

Requirements (verify before build):
- Docker Desktop must be running on the dev machine
- `docker login ghcr.io` must have been performed once with a PAT that has
  `write:packages` scope — the login persists across invocations

If the build fails:
- Do NOT mark the prompt DONE
- Output: `PROMPT FAILED: <version> — docker build: <first error line>`
- Stop immediately. The operator will inspect and either fix the Dockerfile
  or the credentials, then retry.

If the push fails but the build succeeded:
- Do NOT mark the prompt DONE
- Output: `PROMPT FAILED: <version> — docker push: <error>`
- Common causes: expired PAT, network, GHCR rate limit. Operator fixes and retries.

### Step 6 — Mark DONE in INDEX.md

Update cc_prompts/INDEX.md: change the status column for this prompt
from `PENDING` to `DONE (SHA)` where SHA = `git rev-parse --short HEAD`.

Example — change:
  | CC_PROMPT_v2.8.0.md | v2.8.0 | ... | PENDING |
To:
  | CC_PROMPT_v2.8.0.md | v2.8.0 | ... | DONE (abc1234) |

Then commit the index update:
```bash
git add cc_prompts/INDEX.md
git commit -m "chore: mark v<version> DONE in prompt queue"
git push origin main
```

### Step 7 — STOP

After marking DONE and pushing the index update, output a single line:
  PROMPT COMPLETE: <version>

Then stop. Do not read the next prompt. Do not continue to the next item.
The bash script will invoke you again for the next prompt if needed.

---

## Error handling

If any step fails:
- Do not mark the prompt DONE
- Output: PROMPT FAILED: <version> — <reason>
- Stop immediately

---

## Important notes

- Project root: D:\claude_code\ai-local-agent-tools
- Read files before editing — prompts reference existing functions
- Frozensets: append to existing set, don't replace it
- Test imports: `python -c "from api.db.entity_history import init_entity_history"`
- One prompt per invocation. The loop is in run_queue.sh, not here.
