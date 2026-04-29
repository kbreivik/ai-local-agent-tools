# DEATHSTAR Prompt Queue Runner — Single-prompt instruction

You are implementing ONE specific prompt for the DEATHSTAR project.
The prompt file and version are specified below by the calling script.

DO NOT loop to the next prompt. Implement ONLY the prompt provided.
The runner script (run_queue.py) controls iteration and status tracking —
your job is one prompt.

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
the existing structure. Use exact function names and file paths from
the prompt. Never rewrite a whole file when the prompt says to add or
update a section.

### Step 3 — Implement all changes

Make every change described in the prompt. If the prompt says NEW FILE,
create it. If it says "add after X" or "replace Y with Z", do exactly
that. Update the VERSION file to the version number in the prompt header.

### Step 4 — Verify

Run syntax checks on changed Python files:

    cd D:\claude_code\ai-local-agent-tools
    python -m py_compile <any changed .py files>

If py_compile fails, fix the error before committing.

### Step 5 — Commit and push

Use the exact commit message from the prompt's ## Commit section.

    git add -A
    git commit -m "<message from prompt>"
    git push origin main

Verify push succeeded:

    git log --oneline -1

### Step 6 — STOP

After the feature commit is pushed, output a single line:

    PROMPT COMPLETE: <version>

Then stop. Do not read the next prompt. Do not edit
cc_prompts/INDEX.md, cc_prompts/QUEUE_STATE.json, or
cc_prompts/QUEUE_STATUS.md — the runner script owns those entirely.
The runner will invoke you again for the next prompt if needed.

---

## Error handling

If any step fails:
- Do not proceed to commit
- Output: PROMPT FAILED: <version> — <reason>
- Stop immediately

---

## Important notes

- Project root: D:\claude_code\ai-local-agent-tools
- Read files before editing — prompts reference existing functions
- Frozensets: append to existing set, don't replace it
- Test imports: `python -c "from api.db.entity_history import init_entity_history"`
- One prompt per invocation. The loop is in run_queue.py, not here.
- INDEX.md, QUEUE_STATE.json, QUEUE_STATUS.md are the runner's domain — never touch them.
