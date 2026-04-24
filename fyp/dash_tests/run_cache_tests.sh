#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

COVERAGE_MIN="${COVERAGE_MIN:-100}"

if [[ -n "${PYTHON_BIN:-}" ]]; then
  PYTHON="$PYTHON_BIN"
elif [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  PYTHON="$REPO_ROOT/.venv/bin/python"
else
  PYTHON="python3"
fi

"$PYTHON" -m pytest \
  fyp/dash_tests/test_cache_implementations.py \
  --cov=fyp.dash_scripts.cache_sim \
  --cov=fyp.dash_scripts.cache_sim_source_seen \
  --cov-report=term-missing \
  --cov-fail-under="$COVERAGE_MIN"
