#!/usr/bin/env bash
set -euo pipefail

print_usage() {
  cat <<'EOF'
Usage:
  bash fyp/dash_scripts/run_cache_sim_congestion_synthetic.sh [options]

Options:
  -d, --dataset NAME        Process one dataset or family shorthand (see below)
  -p, --protocol NAME       Transport protocol: ndp, hpcc, or tcp (default: all three)
  -f, --fast                (no-op for congestion sim; kept for interface consistency)
      --no-fast
      --range-threshold N   Forward when |new_qs - cached_qs| > N bytes (default: 8192)
      --key-level MODE      switch | flow (default: switch)
      --capacity-plots      Generate capacity CSV and plots (default: off)
  -h, --help                Show this help

Dataset family shorthands for --dataset:
  incast_mono_n / a2a_mono_n                   all flow-size sweep datasets
  incast_heavytail_burst_n / a2a_heavytail_burst_n   all burst sweep datasets (NDP only)
  incast_pareto_alpha_n / a2a_pareto_alpha_n   all Pareto alpha sweep datasets
  incast_heavytail_sigma_n / a2a_heavytail_sigma_n  all heavytail sigma sweep datasets
  incast_heavytail_temp_n / a2a_heavytail_temp_n    all heavytail temporal sweep datasets

Environment variables:
  PROTOCOL             Equivalent to --protocol (ndp/hpcc/tcp)
  DATASET              Equivalent to --dataset
  TARGET_PATTERN       Deprecated legacy alias for DATASET
  RANGE_THRESHOLD      Equivalent to --range-threshold
  KEY_LEVEL            Equivalent to --key-level
  CAPACITY_PLOTS       Equivalent to --capacity-plots (1/0, default: 0)
EOF
}

DATASET="${DATASET:-}"
TARGET_PATTERN="${TARGET_PATTERN:-}"
LOW_TEMP_LOCALITY="${LOW_TEMP_LOCALITY:-0}"
PROTOCOLS="${PROTOCOL:-ndp hpcc tcp}"
RANGE_THRESHOLD="${RANGE_THRESHOLD:-8192}"
KEY_LEVEL="${KEY_LEVEL:-switch}"
CAPACITY_PLOTS="${CAPACITY_PLOTS:-0}"

is_supported_dataset_name() {
  local name="$1"
  if [[ "$name" =~ ^(incast|a2a)_(mono|bimodal|pareto|exponential_skewed|heavytail)$ ]]; then
    return 0
  fi
  if [[ "$name" =~ ^(incast|a2a)_mono_[0-9]+$ ]]; then
    return 0
  fi
  if [[ "$name" =~ ^(incast|a2a)_pareto_(alpha|temp)_[0-9]+(p[0-9]+)?$ ]]; then
    return 0
  fi
  if [[ "$name" =~ ^(incast|a2a)_heavytail_(sigma|temp)_[0-9]+(p[0-9]+)?$ ]]; then
    return 0
  fi
  if [[ "$name" =~ ^(incast|a2a)_heavytail_burst_[0-9]+$ ]]; then
    return 0
  fi
  return 1
}

is_base_dataset_name() {
  local name="$1"
  [[ "$name" =~ ^(incast|a2a)_(mono|bimodal|pareto|exponential_skewed|heavytail)$ ]]
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -d|--dataset)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --dataset requires a value" >&2; exit 1
      fi
      DATASET="$2"; shift 2 ;;
    -p|--protocol)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --protocol requires a value" >&2; exit 1
      fi
      PROTOCOLS="$2"; shift 2 ;;
    -f|--fast|--no-fast)
      shift ;;
    --range-threshold)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --range-threshold requires a value" >&2; exit 1
      fi
      RANGE_THRESHOLD="$2"; shift 2 ;;
    --key-level)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --key-level requires a value" >&2; exit 1
      fi
      KEY_LEVEL="$2"; shift 2 ;;
    --capacity-plots)
      CAPACITY_PLOTS=1; shift ;;
    -h|--help)
      print_usage; exit 0 ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      print_usage; exit 1 ;;
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

for proto in $PROTOCOLS; do
  if [[ "$proto" != "ndp" && "$proto" != "hpcc" && "$proto" != "tcp" ]]; then
    echo "ERROR: --protocol must be ndp, hpcc, or tcp (got: $proto)" >&2; exit 1
  fi
done

if [[ "$KEY_LEVEL" != "switch" && "$KEY_LEVEL" != "flow" ]]; then
  echo "ERROR: --key-level must be switch or flow" >&2; exit 1
fi
if ! [[ "$RANGE_THRESHOLD" =~ ^[0-9]+$ ]]; then
  echo "ERROR: --range-threshold must be a non-negative integer" >&2; exit 1
fi
if [[ "$CAPACITY_PLOTS" != "0" && "$CAPACITY_PLOTS" != "1" ]]; then
  echo "ERROR: CAPACITY_PLOTS must be 0 or 1" >&2; exit 1
fi

LOW_TEMP_SUFFIX="${LOW_TEMP_SUFFIX:-low_temp_locality}"
CAPACITY_PLOT_CAPACITIES="${CAPACITY_PLOT_CAPACITIES:-}"
CAPACITY_PLOT_MIN_CAPACITY="${CAPACITY_PLOT_MIN_CAPACITY:-512}"

is_low_dataset_name() {
  local name="$1"
  [[ "$name" == *"_${LOW_TEMP_SUFFIX}" ]]
}

if [[ "$LOW_TEMP_LOCALITY" != "0" && "$LOW_TEMP_LOCALITY" != "1" ]]; then
  echo "ERROR: LOW_TEMP_LOCALITY must be 0 or 1" >&2; exit 1
fi

normalize_dataset_alias() {
  local name="$1"
  case "$name" in
    incast)                        echo "incast_mono" ;;
    a2a)                           echo "a2a_mono" ;;
    incast_${LOW_TEMP_SUFFIX})     echo "incast_mono_${LOW_TEMP_SUFFIX}" ;;
    a2a_${LOW_TEMP_SUFFIX})        echo "a2a_mono_${LOW_TEMP_SUFFIX}" ;;
    *)                             echo "$name" ;;
  esac
}

DATASET_ORIG="$DATASET"
if [[ -n "$DATASET_ORIG" ]]; then
  DATASET_ORIG="$(normalize_dataset_alias "$DATASET_ORIG")"
fi

FAMILY_PREFIX=""
DATASET_NORM="$DATASET_ORIG"
if [[ -n "$DATASET_NORM" && "$DATASET_NORM" =~ ^(incast|a2a)_mono_n$ ]]; then
  FAMILY_PREFIX="${BASH_REMATCH[1]}_mono_"; DATASET_NORM=""
elif [[ -n "$DATASET_NORM" && "$DATASET_NORM" =~ ^(incast|a2a)_heavytail_burst_n$ ]]; then
  FAMILY_PREFIX="${BASH_REMATCH[1]}_heavytail_burst_"; DATASET_NORM=""
elif [[ -n "$DATASET_NORM" && "$DATASET_NORM" =~ ^(incast|a2a)_pareto_alpha_n$ ]]; then
  FAMILY_PREFIX="${BASH_REMATCH[1]}_pareto_alpha_"; DATASET_NORM=""
elif [[ -n "$DATASET_NORM" && "$DATASET_NORM" =~ ^(incast|a2a)_heavytail_sigma_n$ ]]; then
  FAMILY_PREFIX="${BASH_REMATCH[1]}_heavytail_sigma_"; DATASET_NORM=""
elif [[ -n "$DATASET_NORM" && "$DATASET_NORM" =~ ^(incast|a2a)_heavytail_temp_n$ ]]; then
  FAMILY_PREFIX="${BASH_REMATCH[1]}_heavytail_temp_"; DATASET_NORM=""
elif [[ -n "$DATASET_NORM" ]]; then
  if ! is_supported_dataset_name "$DATASET_NORM"; then
    echo "ERROR: unsupported synthetic dataset '$DATASET_NORM'" >&2; exit 1
  fi
fi

for PROTOCOL in $PROTOCOLS; do
  echo "=== Protocol: $PROTOCOL ==="

  OUT_DIR="${OUT_DIR:-fyp/dash_results/synthetic/${PROTOCOL}/cache_sim/congestion}"
  CAPACITY_DIR="${OUT_DIR}/capacity"
  CAPACITY_PLOTS_DIR="${CAPACITY_DIR}/plots"
  LOG_ROOT="${LOG_ROOT:-fyp/dash_dataset/synthetic/${PROTOCOL}}"

  DATASET="$DATASET_NORM"
  if [[ -n "$DATASET" ]]; then
    if [[ "$LOW_TEMP_LOCALITY" == "1" ]] && ! is_low_dataset_name "$DATASET" && is_base_dataset_name "$DATASET"; then
      DATASET="${DATASET}_${LOW_TEMP_SUFFIX}"
    fi
  fi

  mkdir -p "$OUT_DIR" "$CAPACITY_DIR" "$CAPACITY_PLOTS_DIR"

  patterns=()
  if [[ -n "$DATASET" ]]; then
    patterns=("$DATASET")
  elif [[ -n "$FAMILY_PREFIX" ]]; then
    while IFS= read -r log; do
      [[ -n "$log" ]] || continue
      name="$(basename "$log")"
      name="${name#log_}"; name="${name%.txt}"
      is_supported_dataset_name "$name" || continue
      patterns+=("$name")
    done < <(find "$LOG_ROOT" -maxdepth 1 -type f -name "log_${FAMILY_PREFIX}*.txt" | sort)
  else
    while IFS= read -r log; do
      [[ -n "$log" ]] || continue
      name="$(basename "$log")"
      name="${name#log_}"; name="${name%.txt}"
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
    log="$LOG_ROOT/log_${p}.txt"
    csv="$OUT_DIR/results_synthetic_congestion_${p}.csv"
    if [[ ! -f "$log" ]]; then
      echo "Skipping missing input: $log"
      continue
    fi
    echo "== congestion INT sweep [$PROTOCOL]: $p =="

    sim_cmd=(python3 fyp/dash_scripts/cache_sim_congestion_int.py "$log"
      --sweep
      --quiet-table
      --range-threshold "$RANGE_THRESHOLD"
      --key-level "$KEY_LEVEL"
      --csv "$csv")

    if [[ "$CAPACITY_PLOTS" == "1" ]]; then
      capacity_csv="$CAPACITY_DIR/results_synthetic_congestion_${p}_capacity.csv"
      dataset_plots_dir="${CAPACITY_PLOTS_DIR}/${p}"
      mkdir -p "$dataset_plots_dir"
      sim_cmd+=(--capacity-csv "$capacity_csv")
      "${sim_cmd[@]}"
      plot_cmd=(python3 fyp/dash_scripts/plot_cache_capacity.py "$capacity_csv"
        --out-dir "$dataset_plots_dir"
        --prefix "synthetic_congestion_${p}_capacity"
        --min-capacity "$CAPACITY_PLOT_MIN_CAPACITY")
      [[ -n "$CAPACITY_PLOT_CAPACITIES" ]] && plot_cmd+=(--capacities "$CAPACITY_PLOT_CAPACITIES")
      "${plot_cmd[@]}"
    else
      "${sim_cmd[@]}"
    fi
  done

  echo "Done [$PROTOCOL]. Congestion CSV outputs are under: $OUT_DIR"
done
