# DEATHSTAR sensor stack — Makefile entrypoints.
#
# `make check`        — full human-readable run, every tool's native output.
# `make check-agent`  — agent-optimized output via scripts/check_sensors.py
#                       (failures only, one per line, with HINTs).
#
# Both targets exit non-zero on any failure. Missing tools are reported
# but do not fail the run — install with `make sensors-install`.

PY_TARGETS := api mcp_server scripts
RUFF_CONFIG := .ruff.toml
ESLINT_CONFIG := .eslintrc.sensors.json
GITLEAKS_CONFIG := .gitleaks.toml
GUI_DIR := gui

.PHONY: check check-agent check-all sensors-install ruff bandit gitleaks eslint mypy

# `make check` excludes mypy by default — codebase is largely untyped, so a
# full mypy pass produces noise. Use `make check-all` (or `make mypy`) to opt in.
check: ruff bandit gitleaks eslint
	@echo ""
	@echo "================================================================"
	@echo "  DEATHSTAR sensor stack: default check complete (mypy skipped)."
	@echo "================================================================"

check-all: ruff bandit gitleaks eslint mypy
	@echo ""
	@echo "================================================================"
	@echo "  DEATHSTAR sensor stack: full check complete (incl. mypy)."
	@echo "================================================================"

ruff:
	@echo "── ruff ────────────────────────────────────────────────────────"
	@command -v ruff >/dev/null 2>&1 || { echo "  ruff not installed (pip install ruff)"; exit 0; }
	ruff check --no-cache --config $(RUFF_CONFIG) $(PY_TARGETS)

bandit:
	@echo "── bandit ──────────────────────────────────────────────────────"
	@command -v bandit >/dev/null 2>&1 || { echo "  bandit not installed (pip install bandit)"; exit 0; }
	bandit -c .bandit -r $(PY_TARGETS) --severity-level medium --confidence-level medium

gitleaks:
	@echo "── gitleaks ────────────────────────────────────────────────────"
	@command -v gitleaks >/dev/null 2>&1 || { echo "  gitleaks not installed (see github.com/gitleaks/gitleaks)"; exit 0; }
	gitleaks detect --no-banner --no-git --config $(GITLEAKS_CONFIG) --source . --redact --verbose

eslint:
	@echo "── eslint (sensors) ────────────────────────────────────────────"
	@if [ ! -d "$(GUI_DIR)/node_modules" ]; then \
		echo "  $(GUI_DIR)/node_modules missing — run \`npm install\` in $(GUI_DIR)/"; \
		exit 0; \
	fi
	@python scripts/check_sensors.py --only eslint

mypy:
	@echo "── mypy ────────────────────────────────────────────────────────"
	@command -v mypy >/dev/null 2>&1 || { echo "  mypy not installed (pip install mypy)"; exit 0; }
	mypy --no-color-output --show-error-codes --ignore-missing-imports \
		--follow-imports=silent \
		--exclude '(^|/)(tests?|node_modules|gui|data|logs|\.venv|venv)(/|$$)' \
		$(PY_TARGETS)

check-agent:
	@python scripts/check_sensors.py

sensors-install:
	@echo "Installing Python sensors via pip..."
	pip install --quiet ruff bandit mypy
	@echo "gitleaks: install via your package manager (brew/scoop/apt)."
	@echo "eslint: run \`npm install\` in $(GUI_DIR)/"
