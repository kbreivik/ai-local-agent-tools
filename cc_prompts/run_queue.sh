#!/bin/bash
# DEATHSTAR Prompt Queue Runner
# Invokes Claude Code in agentic mode to work through cc_prompts/ queue sequentially.
#
# Usage:
#   bash cc_prompts/run_queue.sh              # run all pending prompts
#   bash cc_prompts/run_queue.sh --dry-run    # show pending prompts without executing
#   bash cc_prompts/run_queue.sh --one        # run only the next pending prompt, then stop

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
INDEX_FILE="$SCRIPT_DIR/INDEX.md"
RUNNER_FILE="$SCRIPT_DIR/QUEUE_RUNNER.md"

# ── Argument parsing ──────────────────────────────────────────────────────────

DRY_RUN=false
ONE_ONLY=false
for arg in "$@"; do
    case $arg in
        --dry-run) DRY_RUN=true ;;
        --one)     ONE_ONLY=true ;;
        --help)
            echo "Usage: bash cc_prompts/run_queue.sh [--dry-run] [--one]"
            echo "  --dry-run  Show pending prompts without executing"
            echo "  --one      Execute only the next pending prompt"
            exit 0
            ;;
    esac
done

# ── Helpers ───────────────────────────────────────────────────────────────────

log()  { echo "[queue] $*"; }
err()  { echo "[queue] ERROR: $*" >&2; exit 1; }
warn() { echo "[queue] WARN:  $*"; }

pending_count() {
    grep -c "| PENDING" "$INDEX_FILE" 2>/dev/null || echo 0
}

next_pending_file() {
    grep "| PENDING" "$INDEX_FILE" | head -1 \
        | sed 's/.*|\s*\(CC_PROMPT[^|]*\.md\)\s*|.*/\1/' | tr -d ' '
}

next_pending_version() {
    grep "| PENDING" "$INDEX_FILE" | head -1 \
        | sed 's/.*|\s*\(v[0-9][0-9.]*\)\s*|.*/\1/' | tr -d ' '
}

# ── Preflight checks ──────────────────────────────────────────────────────────

cd "$PROJECT_ROOT"

log "Project root: $PROJECT_ROOT"
log "Index:        $INDEX_FILE"

if ! command -v claude &>/dev/null; then
    err "claude CLI not found. Install: npm install -g @anthropic-ai/claude-code"
fi

if ! git rev-parse --git-dir &>/dev/null; then
    err "Not in a git repository"
fi

log "Git branch: $(git branch --show-current)"

MODIFIED_TRACKED=$(git diff --name-only)
if [[ -n "$MODIFIED_TRACKED" ]]; then
    warn "Modified tracked files detected before queue run:"
    echo "$MODIFIED_TRACKED"
    read -p "[queue] Continue anyway? (y/N) " -n 1 -r
    echo
    [[ $REPLY =~ ^[Yy]$ ]] || exit 1
fi

# ── Dry run ───────────────────────────────────────────────────────────────────

if $DRY_RUN; then
    COUNT=$(pending_count)
    log "Queue status — $COUNT prompt(s) PENDING:"
    echo ""
    printf "  %-10s %-73s %-9s\n" "Version" "Theme" "Status"
    printf "  %-10s %-73s %-9s\n" "-------" "-----" "------"
    grep "| PENDING\|| DONE" "$INDEX_FILE" | while IFS='|' read -r _ file ver theme status _; do
        ver=$(echo "$ver" | xargs)
        theme=$(echo "$theme" | xargs | cut -c1-70)
        status=$(echo "$status" | xargs)
        printf "  %-10s %-73s %-9s\n" "$ver" "$theme" "$status"
    done
    echo ""
    exit 0
fi

# ── Main queue loop ───────────────────────────────────────────────────────────

RUN_COUNT=0
MAX_RUNS=10

while true; do
    COUNT=$(pending_count)
    if [[ "$COUNT" -eq 0 ]]; then
        log "Queue complete — all prompts done."
        break
    fi

    if [[ $RUN_COUNT -ge $MAX_RUNS ]]; then
        log "Safety cap reached ($MAX_RUNS runs). Re-run to continue."
        break
    fi

    NEXT_FILE=$(next_pending_file)
    NEXT_VER=$(next_pending_version)
    PROMPT_PATH="$SCRIPT_DIR/$NEXT_FILE"

    if [[ -z "$NEXT_FILE" ]]; then
        err "Could not parse next PENDING file from INDEX.md."
    fi

    if [[ ! -f "$PROMPT_PATH" ]]; then
        err "Prompt file not found: $PROMPT_PATH"
    fi

    log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    log "Running: $NEXT_VER — $NEXT_FILE  ($((COUNT)) pending)"
    log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    BEFORE_HASH=$(git rev-parse HEAD)

    # Write task to temp file and pipe via stdin with --print.
    # Passing task as a positional arg leaves claude in interactive REPL mode
    # (requiring "exit" to continue). --print + stdin is the non-interactive mode.
    TMPFILE=$(mktemp /tmp/deathstar_queue_XXXXXX.txt)

    cat > "$TMPFILE" << TASK_EOF
You are running in automated queue mode for the DEATHSTAR project.

$(cat "$RUNNER_FILE")

---

The prompt to implement right now is: $NEXT_FILE (version $NEXT_VER)

Prompt content:

$(cat "$PROMPT_PATH")

After implementing and pushing, update cc_prompts/INDEX.md: change the status
for $NEXT_FILE from 'PENDING' to 'DONE (SHA)' where SHA is the short git hash,
then commit and push that index change too.
TASK_EOF

    if claude --dangerously-skip-permissions --print < "$TMPFILE"; then
        rm -f "$TMPFILE"
        AFTER_HASH=$(git rev-parse HEAD)
        if [[ "$BEFORE_HASH" == "$AFTER_HASH" ]]; then
            warn "Git hash unchanged after CC run — $NEXT_FILE may not have committed."
            warn "Check: git log --oneline -5"
            warn "Queue paused. Fix and re-run."
            exit 1
        fi
        SHORT=$(git rev-parse --short HEAD)
        log "✓ $NEXT_VER committed as $SHORT"
    else
        rm -f "$TMPFILE"
        err "claude exited non-zero for $NEXT_FILE — queue stopped."
    fi

    RUN_COUNT=$((RUN_COUNT + 1))

    if $ONE_ONLY; then
        log "--one flag set, stopping after first prompt."
        break
    fi

    log "Pausing 3s before next prompt..."
    sleep 3
done

log ""
log "Session summary: $RUN_COUNT prompt(s) executed."
log "Remaining pending: $(pending_count)"
git log --oneline -5
