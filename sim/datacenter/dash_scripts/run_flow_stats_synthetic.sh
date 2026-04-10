#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash dash_scripts/run_flow_stats_synthetic.sh [options]

Options:
  -d, --dataset NAME        Only analyze one dataset (repeatable)
  -l, --low-temp-locality   Analyze low-temp-locality variants
  -t, --top N               Top N flows to print per report (default: 20)
  -m, --max-records N       Max parsed records per logfile (default: 0 = all)
  -o, --out-dir DIR         Output directory (default: dash_results/synthetic/flow_stats)
      --no-concurrency      Disable concurrency estimation
      --no-aggregate        Skip all-selected aggregate report
  -h, --help                Show this help

Examples:
  bash dash_scripts/run_flow_stats_synthetic.sh
  bash dash_scripts/run_flow_stats_synthetic.sh --dataset incast_mono
  bash dash_scripts/run_flow_stats_synthetic.sh --low-temp-locality --dataset a2a_mono
EOF
}

TOP_N=20
MAX_RECORDS=0
OUT_DIR="dash_results/synthetic/flow_stats"
WITH_CONCURRENCY=1
WITH_AGGREGATE=1
LOW_TEMP=0
DATASETS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    -d|--dataset)
      [[ $# -ge 2 ]] || { echo "ERROR: --dataset requires a value" >&2; exit 1; }
      DATASETS+=("$2")
      shift 2
      ;;
    -l|--low-temp-locality)
      LOW_TEMP=1
      shift
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

mkdir -p "$OUT_DIR"

FLOW_ARGS=(--top "$TOP_N" --max-records "$MAX_RECORDS")
if [[ "$WITH_CONCURRENCY" -eq 1 ]]; then
  FLOW_ARGS+=(--concurrency)
fi
if [[ "$LOW_TEMP" -eq 1 ]]; then
  FLOW_ARGS+=(--low-temp-locality)
fi

if [[ ${#DATASETS[@]} -eq 0 ]]; then
  if [[ "$LOW_TEMP" -eq 1 ]]; then
    DATASETS=(
      incast_mono_low_temp_locality
      a2a_mono_low_temp_locality
      incast_bimodal_low_temp_locality
      a2a_bimodal_low_temp_locality
      incast_pareto_low_temp_locality
      a2a_pareto_low_temp_locality
      incast_pareto_heavy_low_temp_locality
      a2a_pareto_heavy_low_temp_locality
      incast_lognormal_skewed_low_temp_locality
      a2a_lognormal_skewed_low_temp_locality
      incast_exponential_skewed_low_temp_locality
      a2a_exponential_skewed_low_temp_locality
    )
  else
    DATASETS=(
      incast_mono
      a2a_mono
      incast_bimodal
      a2a_bimodal
      incast_pareto
      a2a_pareto
      incast_pareto_heavy
      a2a_pareto_heavy
      incast_lognormal_skewed
      a2a_lognormal_skewed
      incast_exponential_skewed
      a2a_exponential_skewed
    )
  fi
fi

logs=()
for ds in "${DATASETS[@]}"; do
  logfile="dash_dataset/synthetic/log_${ds}.txt"
  if [[ ! -f "$logfile" ]]; then
    echo "Skipping missing logfile: $logfile" >&2
    continue
  fi
  logs+=("$logfile")

  out_txt="$OUT_DIR/${ds}_flow_stats.txt"
  out_csv="$OUT_DIR/${ds}_flow_stats.csv"

  cmd=(python3 dash_scripts/flow_stats.py "$logfile" --csv "$out_csv")
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
  cmd=(python3 dash_scripts/flow_stats.py --csv "$all_csv")
  cmd+=("${FLOW_ARGS[@]}")
  cmd+=("${logs[@]}")
  "${cmd[@]}" > "$all_txt"
  echo "Wrote aggregate: $all_txt"
  echo "Wrote aggregate: $all_csv"
fi

echo "Done. Synthetic flow stats are under: $OUT_DIR"
