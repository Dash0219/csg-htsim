#!/usr/bin/env bash
set -euo pipefail

print_usage() {
  cat <<'EOF'
Usage:
  bash dash_scripts/run_cache_sim_synthetic.sh [options]

Options:
  -d, --dataset NAME        Process one synthetic dataset family (example: a2a_pareto)
  -p, --protocol NAME       Transport protocol: ndp or hpcc (default: ndp)
  -f, --fast                Use the optimized cache simulator (default)
      --no-fast             Disable the optimized cache simulator
  -h, --help           Show this help

Environment variables:
  PROTOCOL             Equivalent to --protocol (ndp/hpcc)
  FAST                 Equivalent to --fast (1/0, default: 1)
  DATASET              Equivalent to --dataset
  TARGET_PATTERN       Deprecated legacy alias for DATASET
EOF
}

DATASET="${DATASET:-}"
TARGET_PATTERN="${TARGET_PATTERN:-}"
LOW_TEMP_LOCALITY="${LOW_TEMP_LOCALITY:-0}"
PROTOCOL="${PROTOCOL:-ndp}"
FAST="${FAST:-1}"

is_flow_size_sweep_dataset() {
  local name="$1"
  [[ "$name" =~ ^(incast|a2a)_mono_[0-9]+$ ]]
}

is_supported_dataset_name() {
  local name="$1"
  if [[ "$name" =~ ^(incast|a2a)_(mono|bimodal|pareto|exponential_skewed)$ ]]; then
    return 0
  fi
  if [[ "$name" =~ ^(incast|a2a)_mono_[0-9]+$ ]]; then
    return 0
  fi
  if [[ "$name" =~ ^(incast|a2a)_pareto_(alpha|temp)_[0-9]+(p[0-9]+)?$ ]]; then
    return 0
  fi
  if [[ "$name" =~ ^(incast|a2a)_mono_burst_[0-9]+$ ]]; then
    return 0
  fi
  return 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -d|--dataset)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --dataset requires a value" >&2
        exit 1
      fi
      DATASET="$2"
      shift 2
      ;;
    -p|--protocol)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --protocol requires a value" >&2
        exit 1
      fi
      PROTOCOL="$2"
      shift 2
      ;;
    -f|--fast)
      FAST=1
      shift
      ;;
    --no-fast)
      FAST=0
      shift
      ;;
    -h|--help)
      print_usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      print_usage
      exit 1
      ;;
  esac
done

if [[ -z "$DATASET" && -n "$TARGET_PATTERN" ]]; then
  DATASET="$TARGET_PATTERN"
  echo "WARN: TARGET_PATTERN is deprecated; use --dataset (or DATASET) instead." >&2
elif [[ -n "$DATASET" && -n "$TARGET_PATTERN" && "$DATASET" != "$TARGET_PATTERN" ]]; then
  echo "ERROR: DATASET ($DATASET) and TARGET_PATTERN ($TARGET_PATTERN) disagree" >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "$PROTOCOL" != "ndp" && "$PROTOCOL" != "hpcc" ]]; then
  echo "ERROR: --protocol must be ndp or hpcc" >&2
  exit 1
fi

OUT_DIR="dash_results/synthetic/${PROTOCOL}/cache_sim/route_changes"
LOG_ROOT="dash_dataset/synthetic/${PROTOCOL}"
LOW_TEMP_SUFFIX="${LOW_TEMP_SUFFIX:-low_temp_locality}"

is_low_dataset_name() {
  local name="$1"
  [[ "$name" == *"_${LOW_TEMP_SUFFIX}" ]]
}

if [[ "$LOW_TEMP_LOCALITY" != "0" && "$LOW_TEMP_LOCALITY" != "1" ]]; then
  echo "ERROR: LOW_TEMP_LOCALITY must be 0 or 1" >&2
  exit 1
fi

if [[ "$FAST" != "0" && "$FAST" != "1" ]]; then
  echo "ERROR: FAST must be 0 or 1" >&2
  exit 1
fi

if [[ "$LOW_TEMP_LOCALITY" == "1" && -n "$DATASET" ]] && ! is_low_dataset_name "$DATASET" && ! is_flow_size_sweep_dataset "$DATASET"; then
  DATASET="${DATASET}_${LOW_TEMP_SUFFIX}"
fi

if [[ "$LOW_TEMP_LOCALITY" == "0" && -n "$DATASET" ]] && is_low_dataset_name "$DATASET"; then
  LOW_TEMP_LOCALITY=1
fi

normalize_dataset_alias() {
  local name="$1"
  case "$name" in
    incast)
      echo "incast_mono"
      ;;
    a2a)
      echo "a2a_mono"
      ;;
    incast_${LOW_TEMP_SUFFIX})
      echo "incast_mono_${LOW_TEMP_SUFFIX}"
      ;;
    a2a_${LOW_TEMP_SUFFIX})
      echo "a2a_mono_${LOW_TEMP_SUFFIX}"
      ;;
    *)
      echo "$name"
      ;;
  esac
}

if [[ -n "$DATASET" ]]; then
  DATASET="$(normalize_dataset_alias "$DATASET")"
  if ! is_supported_dataset_name "$DATASET"; then
    echo "ERROR: unsupported synthetic dataset '$DATASET' for redesigned suite" >&2
    exit 1
  fi
fi

mkdir -p "$OUT_DIR"

patterns=()
if [[ -n "$DATASET" ]]; then
  patterns=("$DATASET")
else
  while IFS= read -r log; do
    [[ -n "$log" ]] || continue
    name="$(basename "$log")"
    name="${name#log_}"
    name="${name%.txt}"
    is_supported_dataset_name "$name" || continue
    if [[ "$LOW_TEMP_LOCALITY" == "1" ]]; then
      is_low_dataset_name "$name" || continue
    else
      is_low_dataset_name "$name" && continue
    fi
    patterns+=("$name")
  done < <(find "$LOG_ROOT" -maxdepth 1 -type f -name 'log_*.txt' | sort)
fi

for p in "${patterns[@]}"; do
  if [[ -n "$DATASET" && "$p" != "$DATASET" ]]; then
    continue
  fi
  log="$LOG_ROOT/log_${p}.txt"
  csv="$OUT_DIR/results_synthetic_${p}.csv"
  if [[ ! -f "$log" ]]; then
    echo "Skipping missing input: $log"
    continue
  fi
  echo "== cache_sim sweep: $p =="
  if [[ "$FAST" == "1" ]]; then
    python3 dash_scripts/cache_sim.py "$log" --sweep --fast --quiet-table --csv "$csv"
  else
    python3 dash_scripts/cache_sim.py "$log" --sweep --quiet-table --csv "$csv"
  fi
done

echo "Done. Route-change CSV outputs are under: $OUT_DIR"
