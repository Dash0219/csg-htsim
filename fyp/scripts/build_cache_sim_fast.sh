#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

DEFAULT_VENV_PY="$ROOT_DIR/../../../.venv/bin/python"
if [[ -x "$DEFAULT_VENV_PY" ]]; then
	PYTHON_BIN="${PYTHON_BIN:-$DEFAULT_VENV_PY}"
else
	PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

"$PYTHON_BIN" -m pip install -q --upgrade pip setuptools wheel cython
"$PYTHON_BIN" setup_cache_sim_fast.py build_ext --inplace

echo "Built cache_sim_fast extension in $ROOT_DIR"
