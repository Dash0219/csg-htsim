#!/usr/bin/env bash
set -euo pipefail

print_usage() {
  cat <<'EOF'
Usage:
  bash fyp/dash_scripts/run_cache_sim_congestion_synthetic.sh [options]

Options:
  -d, --dataset NAME        Process one synthetic dataset family (example: a2a_pareto)
  -p, --protocol NAME       Transport protocol: ndp or hpcc (default: hpcc)
  -f, --fast                Use the optimized cache simulator (default)
      --no-fast             Disable the optimized cache simulator
      --qs-threshold N      Queue-size anomaly threshold in bytes (default: 50000)
      --key-level MODE      switch | flow (default: switch)
      --signature MODE      seen | bucket (default: seen)
      --bucket-bytes N      Bucket width when --signature bucket (default: 8192)
      --range-threshold N   INTCollector-style range detection: forward only when
                            |new_qs - cached_qs| > N bytes. 0 disables (default: 8192)
  -h, --help                Show this help

Environment variables:
  PROTOCOL             Equivalent to --protocol (ndp/hpcc)
  FAST                 Equivalent to --fast (1/0, default: 1)
  DATASET              Equivalent to --dataset
  TARGET_PATTERN       Deprecated legacy alias for DATASET
  QS_THRESHOLD         Equivalent to --qs-threshold
  KEY_LEVEL            Equivalent to --key-level
  SIGNATURE_MODE       Equivalent to --signature
  BUCKET_BYTES         Equivalent to --bucket-bytes
  RANGE_THRESHOLD      Equivalent to --range-threshold
EOF
}

DATASET="${DATASET:-}"
TARGET_PATTERN="${TARGET_PATTERN:-}"
LOW_TEMP_LOCALITY="${LOW_TEMP_LOCALITY:-0}"
PROTOCOL="${PROTOCOL:-hpcc}"
FAST="${FAST:-1}"
QS_THRESHOLD="${QS_THRESHOLD:-50000}"
KEY_LEVEL="${KEY_LEVEL:-switch}"
SIGNATURE_MODE="${SIGNATURE_MODE:-seen}"
BUCKET_BYTES="${BUCKET_BYTES:-8192}"
RANGE_THRESHOLD="${RANGE_THRESHOLD:-8192}"

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

is_base_dataset_name() {
  local name="$1"
  [[ "$name" =~ ^(incast|a2a)_(mono|bimodal|pareto|exponential_skewed)$ ]]
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
    --qs-threshold)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --qs-threshold requires a value" >&2
        exit 1
      fi
      QS_THRESHOLD="$2"
      shift 2
      ;;
    --key-level)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --key-level requires a value" >&2
        exit 1
      fi
      KEY_LEVEL="$2"
      shift 2
      ;;
    --signature)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --signature requires a value" >&2
        exit 1
      fi
      SIGNATURE_MODE="$2"
      shift 2
      ;;
    --bucket-bytes)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --bucket-bytes requires a value" >&2
        exit 1
      fi
      BUCKET_BYTES="$2"
      shift 2
      ;;
    --range-threshold)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --range-threshold requires a value" >&2
        exit 1
      fi
      RANGE_THRESHOLD="$2"
      shift 2
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

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

if [[ "$PROTOCOL" != "ndp" && "$PROTOCOL" != "hpcc" ]]; then
  echo "ERROR: --protocol must be ndp or hpcc" >&2
  exit 1
fi
if [[ "$KEY_LEVEL" != "switch" && "$KEY_LEVEL" != "flow" ]]; then
  echo "ERROR: --key-level must be switch or flow" >&2
  exit 1
fi
if [[ "$SIGNATURE_MODE" != "seen" && "$SIGNATURE_MODE" != "bucket" ]]; then
  echo "ERROR: --signature must be seen or bucket" >&2
  exit 1
fi
if ! [[ "$RANGE_THRESHOLD" =~ ^[0-9]+$ ]]; then
  echo "ERROR: --range-threshold must be a non-negative integer" >&2
  exit 1
fi
if [[ "$RANGE_THRESHOLD" != "0" && "$KEY_LEVEL" != "switch" ]]; then
  echo "ERROR: --range-threshold requires --key-level switch" >&2
  exit 1
fi

OUT_DIR="fyp/dash_results/synthetic/${PROTOCOL}/cache_sim/congestion"
CAPACITY_DIR="${OUT_DIR}/capacity"
CAPACITY_PLOTS_DIR="${CAPACITY_DIR}/plots"
LOG_ROOT="fyp/dash_dataset/synthetic/${PROTOCOL}"
LOW_TEMP_SUFFIX="${LOW_TEMP_SUFFIX:-low_temp_locality}"
CAPACITY_PLOT_CAPACITIES="${CAPACITY_PLOT_CAPACITIES:-}"
CAPACITY_PLOT_MIN_CAPACITY="${CAPACITY_PLOT_MIN_CAPACITY:-512}"

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

if [[ "$LOW_TEMP_LOCALITY" == "1" && -n "$DATASET" ]] && ! is_low_dataset_name "$DATASET" && is_base_dataset_name "$DATASET"; then
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

mkdir -p "$OUT_DIR" "$CAPACITY_DIR" "$CAPACITY_PLOTS_DIR"

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
  dataset_plots_dir="${CAPACITY_PLOTS_DIR}/${p}"
  mkdir -p "$dataset_plots_dir"
  log="$LOG_ROOT/log_${p}.txt"
  csv="$OUT_DIR/results_synthetic_congestion_${p}.csv"
  capacity_csv="$CAPACITY_DIR/results_synthetic_congestion_${p}_capacity.csv"
  if [[ ! -f "$log" ]]; then
    echo "Skipping missing input: $log"
    continue
  fi
  echo "== congestion INT sweep: $p =="
  if [[ "$FAST" == "1" ]]; then
    python3 fyp/dash_scripts/cache_sim_congestion_int.py "$log" \
      --sweep \
      --fast \
      --quiet-table \
      --qs-threshold "$QS_THRESHOLD" \
      --key-level "$KEY_LEVEL" \
      --signature "$SIGNATURE_MODE" \
      --bucket-bytes "$BUCKET_BYTES" \
      --range-threshold "$RANGE_THRESHOLD" \
      --csv "$csv" \
      --capacity-csv "$capacity_csv"
  else
    python3 fyp/dash_scripts/cache_sim_congestion_int.py "$log" \
      --sweep \
      --quiet-table \
      --qs-threshold "$QS_THRESHOLD" \
      --key-level "$KEY_LEVEL" \
      --signature "$SIGNATURE_MODE" \
      --bucket-bytes "$BUCKET_BYTES" \
      --range-threshold "$RANGE_THRESHOLD" \
      --csv "$csv" \
      --capacity-csv "$capacity_csv"
  fi

  plot_cmd=(python3 fyp/dash_scripts/plot_cache_capacity.py "$capacity_csv" --out-dir "$dataset_plots_dir" --prefix "synthetic_congestion_${p}_capacity" --min-capacity "$CAPACITY_PLOT_MIN_CAPACITY")
  if [[ -n "$CAPACITY_PLOT_CAPACITIES" ]]; then
    plot_cmd+=(--capacities "$CAPACITY_PLOT_CAPACITIES")
  fi
  "${plot_cmd[@]}"
done

echo "Done. Congestion CSV outputs are under: $OUT_DIR"
