# DEATHSTAR Prompt Queue Runner
# This is the meta-task for Claude Code to process the cc_prompts queue automatically.
# Run via: bash cc_prompts/run_queue.sh
# Or directly: claude "$(cat cc_prompts/QUEUE_RUNNER.md)"

You are running in automated queue mode for the DEATHSTAR project.
Your job is to work through the cc_prompts/ queue, implementing each PENDING prompt in order,
committing the result to git, and marking it DONE before moving to the next.

## Your loop

Repeat the following until no PENDING items remain in cc_prompts/INDEX.md:

### Step 1 — Find next work item

Read cc_prompts/INDEX.md. Find the FIRST row in the Phase Queue table with status PENDING.
Extract the filename and version. If no PENDING items exist, output "Queue complete — all prompts done."
and stop.

### Step 2 — Read the prompt

Read the prompt file: cc_prompts/<filename>
Understand every change it describes. The prompt is the specification — implement it exactly.

### Step 3 — Implement all changes

Make every file change described in the prompt. The prompt specifies exact functions, code blocks,
and file paths. Do not skip any change. Do not add unrequested changes.

Key rules:
- Read existing file content before editing to understand current state
- Use str_replace_editor or direct file writes as appropriate
- If a file doesn't exist yet and the prompt says NEW FILE, create it
- If a function already exists with the right name, update it in place
- Update the VERSION file to the version number stated in the prompt header

### Step 4 — Verify the implementation

Run these checks before committing:
```bash
cd D:\claude_code\ai-local-agent-tools

# Check Python syntax on any changed .py files
python -m py_compile <changed files>

# Check git status — confirm files are modified
git status

# Confirm VERSION file has the right version
cat VERSION
```

If py_compile fails, fix the syntax error before proceeding. Do not commit broken code.

### Step 5 — Commit and push

Use the exact commit message from the prompt's "## Commit" section.
If the prompt has no commit section, construct one:
  git commit -m "feat: v<version> <short description from prompt title>"

```bash
git add -A
git commit -m "<message from prompt>"
git push origin main
```

Verify push succeeded:
```bash
git log --oneline -1
git status
```

If push fails (network issue, conflict), retry once. If it fails again, stop and report the error.
Do NOT mark the item DONE if push failed.

### Step 6 — Mark DONE in index

Update cc_prompts/INDEX.md: change the status column for this prompt from `PENDING` to `DONE`.
Also add the git commit hash in a new column or as a note — use `git rev-parse --short HEAD`.

The table row goes from:
  | CC_PROMPT_v2.8.0.md | v2.8.0 | AI loop quality... | PENDING |

To:
  | CC_PROMPT_v2.8.0.md | v2.8.0 | AI loop quality... | DONE (abc1234) |

Commit this index update:
```bash
git add cc_prompts/INDEX.md
git commit -m "chore: mark v<version> DONE in prompt queue"
git push origin main
```

### Step 7 — Brief pause and loop

Wait 2 seconds, then return to Step 1 and find the next PENDING item.

---

## Error handling

If any step fails:
- Do not continue to the next prompt
- Do not mark the current prompt DONE
- Output a clear error message explaining what failed and at which step
- Stop the loop

This prevents partial implementations from accumulating.

---

## Important notes

- The project root is: D:\claude_code\ai-local-agent-tools
- Always read existing files before editing — the prompt may reference functions that need updating, not creating
- The prompts reference specific line numbers and function names — use search to find them
- Some prompts say "add after X" or "replace Y with Z" — do exactly that, don't rewrite the whole file
- If a prompt says to add to a frozenset or list, append to the existing set — don't replace it
- Test imports exist: run `python -c "from api.db.entity_history import init_entity_history"` to
  verify new modules are importable before committing
