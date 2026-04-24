# Cache Test Suite

Run from repository root.

## Install test dependencies

```bash
./.venv/bin/python -m pip install -r fyp/dash_tests/requirements.txt
```

## Run tests only

```bash
./.venv/bin/python -m pytest fyp/dash_tests/test_cache_implementations.py -q
```

## Run with coverage gate

```bash
bash fyp/dash_tests/run_cache_tests.sh
```

The coverage gate defaults to `100`.
Override it for iterative development:

```bash
COVERAGE_MIN=80 bash fyp/dash_tests/run_cache_tests.sh
```
