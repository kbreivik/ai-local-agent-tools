#!/usr/bin/env bash
# Checks written Python files for issues.
# Claude Code hook: PostToolUse[Write|Edit]

INPUT=$(cat)
FILE=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('path',''))" 2>/dev/null)

if [[ -z "$FILE" ]] || [[ ! -f "$FILE" ]]; then
  exit 0
fi

# Block hardcoded IPs/secrets in Python
if [[ "$FILE" == *.py ]]; then
  if grep -qE "192\.168\.[0-9]+\.[0-9]+" "$FILE" 2>/dev/null; then
    echo "WARNING: Hardcoded IP detected in $FILE — use env vars instead." >&2
  fi

  if grep -qE "(password|secret|token|api_key)\s*=\s*['\"][^'\"]{4,}" "$FILE" 2>/dev/null; then
    echo "WARNING: Possible hardcoded secret in $FILE" >&2
  fi

  # Check for async in skill modules
  if [[ "$FILE" == */skills/modules/*.py ]]; then
    if grep -q "async def" "$FILE" 2>/dev/null; then
      echo "ERROR: async def found in skill module $FILE — skills must be synchronous." >&2
      exit 1
    fi
    if ! grep -q "SKILL_META" "$FILE" 2>/dev/null; then
      echo "WARNING: SKILL_META not found in $FILE — required for skill modules." >&2
    fi
    if ! grep -q "def execute" "$FILE" 2>/dev/null; then
      echo "WARNING: execute() function not found in $FILE — required for skill modules." >&2
    fi
  fi

  # Syntax check
  if command -v python3 &>/dev/null; then
    python3 -m py_compile "$FILE" 2>&1 | grep -i "syntax\|error" >&2 || true
  fi
fi

exit 0
