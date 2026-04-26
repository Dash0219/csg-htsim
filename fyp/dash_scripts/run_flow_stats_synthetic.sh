#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash fyp/dash_scripts/run_flow_stats_synthetic.sh [options]

Options:
  -d, --dataset NAME        Only analyze one dataset (repeatable)
  -p, --protocol NAME       Transport protocol: ndp or hpcc or tcp (default: ndp)
  -t, --top N               Top N flows to print per report (default: 20)
  -m, --max-records N       Max parsed records per logfile (default: 0 = all)
  -o, --out-dir DIR         Output directory (default: fyp/dash_results/synthetic/<protocol>/flow_stats)
      --low-temp-locality   Select only *_low_temp_locality logs
      --no-concurrency      Disable concurrency estimation
      --no-aggregate        Skip all-selected aggregate report
  -h, --help                Show this help

Examples:
  bash fyp/dash_scripts/run_flow_stats_synthetic.sh
  bash fyp/dash_scripts/run_flow_stats_synthetic.sh --dataset incast_mono
EOF
}

TOP_N=20
MAX_RECORDS=0
OUT_DIR="${OUT_DIR:-}"
PROTOCOL="${PROTOCOL:-ndp}"
WITH_CONCURRENCY=1
WITH_AGGREGATE=1
LOW_TEMP="${LOW_TEMP_LOCALITY:-0}"
DATASETS=()
LOW_TEMP_SUFFIX="${LOW_TEMP_SUFFIX:-low_temp_locality}"

is_low_dataset_name() {
  local name="$1"
  [[ "$name" == *"_${LOW_TEMP_SUFFIX}" ]]
}

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

is_base_dataset_name() {
  local name="$1"
  [[ "$name" =~ ^(incast|a2a)_(mono|bimodal|pareto|heavytail|exponential_skewed)$ ]]
}

is_supported_dataset_name() {
  local name="$1"
  local core_name="$name"
  if is_low_dataset_name "$core_name"; then
    core_name="${core_name%_${LOW_TEMP_SUFFIX}}"
  fi
  if [[ "$core_name" =~ ^(incast|a2a)_(mono|bimodal|pareto|heavytail|exponential_skewed)$ ]]; then
    return 0
  fi
  if [[ "$core_name" =~ ^(incast|a2a)_mono_[0-9]+$ ]]; then
    return 0
  fi
  if [[ "$core_name" =~ ^(incast|a2a)_heavytail_burst_[0-9]+$ ]]; then
    return 0
  fi
  if [[ "$core_name" =~ ^(incast|a2a)_pareto_(alpha|temp)_[0-9]+(p[0-9]+)?$ ]]; then
    return 0
  fi
  if [[ "$core_name" =~ ^(incast|a2a)_heavytail_sigma_[0-9]+(p[0-9]+)?$ ]]; then
    return 0
  fi
  return 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -d|--dataset)
      [[ $# -ge 2 ]] || { echo "ERROR: --dataset requires a value" >&2; exit 1; }
      DATASETS+=("$2")
      shift 2
      ;;
    -p|--protocol)
      [[ $# -ge 2 ]] || { echo "ERROR: --protocol requires a value" >&2; exit 1; }
      PROTOCOL="$2"
      shift 2
      ;;
    -t|--top)
      [[ $# -ge 2 ]] || { echo "ERROR: --top requires a value" >&2; exit 1; }
      TOP_N="$2"
      shift 2
      ;;
    -m|--max-records)
      [[ $# -ge 2 ]] || { echo "ERROR: --max-records requires a value" >&2; exit 1; }
      MAX_RECORDS="$2"
      shift 2
      ;;
    -o|--out-dir)
      [[ $# -ge 2 ]] || { echo "ERROR: --out-dir requires a value" >&2; exit 1; }
      OUT_DIR="$2"
      shift 2
      ;;
    --low-temp-locality)
      LOW_TEMP=1
      shift
      ;;
    --no-concurrency)
      WITH_CONCURRENCY=0
      shift
      ;;
    --no-aggregate)
      WITH_AGGREGATE=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ "$PROTOCOL" != "ndp" && "$PROTOCOL" != "hpcc" && "$PROTOCOL" != "tcp" ]]; then
  echo "ERROR: --protocol must be ndp or hpcc or tcp" >&2
  exit 1
fi
if [[ "$LOW_TEMP" != "0" && "$LOW_TEMP" != "1" ]]; then
  echo "ERROR: LOW_TEMP_LOCALITY must be 0 or 1" >&2
  exit 1
fi

OUT_DIR="${OUT_DIR:-fyp/dash_results/synthetic/${PROTOCOL}/flow_stats}"
LOG_ROOT="fyp/dash_dataset/synthetic/${PROTOCOL}"

mkdir -p "$OUT_DIR"

FLOW_ARGS=(--top "$TOP_N" --max-records "$MAX_RECORDS")
if [[ "$WITH_CONCURRENCY" -eq 1 ]]; then
  FLOW_ARGS+=(--concurrency)
fi
if [[ "$LOW_TEMP" -eq 1 ]]; then
  FLOW_ARGS+=(--low-temp-locality)
fi

if [[ ${#DATASETS[@]} -gt 0 ]]; then
  normalized=()
  for ds in "${DATASETS[@]}"; do
    ds="$(normalize_dataset_alias "$ds")"
    if [[ "$LOW_TEMP" == "1" ]] && ! is_low_dataset_name "$ds" && is_base_dataset_name "$ds"; then
      ds="${ds}_${LOW_TEMP_SUFFIX}"
    fi
    normalized+=("$ds")
  done
  DATASETS=("${normalized[@]}")
else
  while IFS= read -r log; do
    [[ -n "$log" ]] || continue
    ds="$(basename "$log")"
    ds="${ds#log_}"
    ds="${ds%.txt}"
    is_supported_dataset_name "$ds" || continue
    if [[ "$LOW_TEMP" == "1" ]]; then
      is_low_dataset_name "$ds" || continue
    else
      is_low_dataset_name "$ds" && continue
    fi
    DATASETS+=("$ds")
  done < <(find "$LOG_ROOT" -maxdepth 1 -type f -name 'log_*.txt' | sort)
fi

logs=()
for ds in "${DATASETS[@]}"; do
  if ! is_supported_dataset_name "$ds"; then
    echo "Skipping unsupported synthetic dataset selector: $ds" >&2
    continue
  fi
  logfile="$LOG_ROOT/log_${ds}.txt"
  if [[ ! -f "$logfile" ]]; then
    echo "Skipping missing logfile: $logfile" >&2
    continue
  fi
  logs+=("$logfile")

  out_txt="$OUT_DIR/${ds}_flow_stats.txt"
  out_csv="$OUT_DIR/${ds}_flow_stats.csv"

  cmd=(python3 fyp/dash_scripts/flow_stats.py "$logfile" --csv "$out_csv")
  cmd+=("${FLOW_ARGS[@]}")
  "${cmd[@]}" > "$out_txt"
  echo "Wrote: $out_txt"
  echo "Wrote: $out_csv"
  echo

done

if [[ ${#logs[@]} -eq 0 ]]; then
  echo "ERROR: no existing synthetic logs selected" >&2
  exit 1
fi

if [[ "$WITH_AGGREGATE" -eq 1 ]]; then
  suffix=""
  if [[ "$LOW_TEMP" -eq 1 ]]; then
    suffix="_low_temp_locality"
  fi
  all_txt="$OUT_DIR/synthetic_all_flow_stats${suffix}.txt"
  all_csv="$OUT_DIR/synthetic_all_flow_stats${suffix}.csv"
  cmd=(python3 fyp/dash_scripts/flow_stats.py --csv "$all_csv")
  cmd+=("${FLOW_ARGS[@]}")
  cmd+=("${logs[@]}")
  "${cmd[@]}" > "$all_txt"
  echo "Wrote aggregate: $all_txt"
  echo "Wrote aggregate: $all_csv"
fi

echo "Done. Synthetic flow stats are under: $OUT_DIR"
