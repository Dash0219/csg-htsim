# Cache Test Suite

Run from repository root.

## Install test dependencies

```bash
./.venv/bin/python -m pip install -r fyp/tests/requirements.txt
```

## Run tests only

```bash
./.venv/bin/python -m pytest fyp/tests/test_cache_implementations.py -q
```

## Run with coverage gate

```bash
bash fyp/tests/run_cache_tests.sh
```

The coverage gate defaults to `100`.
Override it for iterative development:

```bash
COVERAGE_MIN=80 bash fyp/tests/run_cache_tests.sh
```
