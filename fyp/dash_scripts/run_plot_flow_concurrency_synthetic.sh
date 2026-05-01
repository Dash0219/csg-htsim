#!/usr/bin/env bash
set -euo pipefail

print_usage() {
  cat <<'EOF'
Usage:
  bash fyp/dash_scripts/run_plot_flow_concurrency_synthetic.sh [options]

Options:
  -d, --dataset NAME        Only plot one synthetic dataset, or a family shorthand:
                              incast_mono_n / a2a_mono_n
                              incast_heavytail_burst_n / a2a_heavytail_burst_n
                              incast_pareto_alpha_n / a2a_pareto_alpha_n
                              incast_heavytail_sigma_n / a2a_heavytail_sigma_n
                              incast_heavytail_temp_n / a2a_heavytail_temp_n
  -p, --protocol NAME       Transport protocol: ndp or hpcc or tcp (default: all three)
  -o, --out-dir DIR         Output directory (default: fyp/dash_results/synthetic/<protocol>/flow_concurrency/plots)
      --prefix NAME         Output filename prefix (default: flow_concurrency)
      --max-records N       Limit parsed records (default: 0 means all)
      --max-plot-intervals N Cap rendered intervals (default: 300000)
      --with-concurrency    Overlay concurrency on temporal plots
      --plot-concurrency    Emit separate concurrency PNG
  -h, --help                Show this help
EOF
}

DATASET="${DATASET:-}"
LOW_TEMP_LOCALITY="${LOW_TEMP_LOCALITY:-0}"
LOW_TEMP_SUFFIX="${LOW_TEMP_SUFFIX:-low_temp_locality}"
PROTOCOLS="${PROTOCOL:-ndp hpcc tcp}"
OUT_DIR="${OUT_DIR:-}"
PREFIX="${PREFIX:-flow_concurrency}"
MAX_RECORDS="${MAX_RECORDS:-0}"
MAX_PLOT_INTERVALS="${MAX_PLOT_INTERVALS:-300000}"
WITH_CONCURRENCY="${WITH_CONCURRENCY:-0}"
PLOT_CONCURRENCY="${PLOT_CONCURRENCY:-0}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -d|--dataset)
      [[ $# -ge 2 ]] || { echo "ERROR: --dataset requires a value" >&2; exit 1; }
      DATASET="$2"
      shift 2
      ;;
    -p|--protocol)
      [[ $# -ge 2 ]] || { echo "ERROR: --protocol requires a value" >&2; exit 1; }
      PROTOCOLS="$2"
      shift 2
      ;;
    -o|--out-dir)
      [[ $# -ge 2 ]] || { echo "ERROR: --out-dir requires a value" >&2; exit 1; }
      OUT_DIR="$2"
      shift 2
      ;;
    --prefix)
      [[ $# -ge 2 ]] || { echo "ERROR: --prefix requires a value" >&2; exit 1; }
      PREFIX="$2"
      shift 2
      ;;
    --max-records)
      [[ $# -ge 2 ]] || { echo "ERROR: --max-records requires a value" >&2; exit 1; }
      MAX_RECORDS="$2"
      shift 2
      ;;
    --max-plot-intervals)
      [[ $# -ge 2 ]] || { echo "ERROR: --max-plot-intervals requires a value" >&2; exit 1; }
      MAX_PLOT_INTERVALS="$2"
      shift 2
      ;;
    --with-concurrency)
      WITH_CONCURRENCY=1
      shift
      ;;
    --plot-concurrency)
      PLOT_CONCURRENCY=1
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

if [[ "$LOW_TEMP_LOCALITY" != "0" && "$LOW_TEMP_LOCALITY" != "1" ]]; then
  echo "ERROR: LOW_TEMP_LOCALITY must be 0 or 1" >&2
  exit 1
fi

if [[ "$LOW_TEMP_LOCALITY" == "1" && -n "$DATASET" && "$DATASET" != *"_${LOW_TEMP_SUFFIX}" ]]; then
  DATASET="${DATASET}_${LOW_TEMP_SUFFIX}"
fi

case "$DATASET" in
  incast)
    DATASET="incast_mono"
    ;;
  a2a)
    DATASET="a2a_mono"
    ;;
  incast_${LOW_TEMP_SUFFIX})
    DATASET="incast_mono_${LOW_TEMP_SUFFIX}"
    ;;
  a2a_${LOW_TEMP_SUFFIX})
    DATASET="a2a_mono_${LOW_TEMP_SUFFIX}"
    ;;
esac

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

for proto in $PROTOCOLS; do
  if [[ "$proto" != "ndp" && "$proto" != "hpcc" && "$proto" != "tcp" ]]; then
    echo "ERROR: --protocol must be ndp or hpcc or tcp (got: $proto)" >&2
    exit 1
  fi
done

OUT_DIR_BASE="${OUT_DIR:-}"
LOG_ROOT_BASE="${LOG_ROOT:-}"
DATASET_ORIG="$DATASET"

for PROTOCOL in $PROTOCOLS; do
  echo "=== Protocol: $PROTOCOL ==="

  OUT_DIR="${OUT_DIR_BASE:-fyp/dash_results/synthetic/${PROTOCOL}/flow_concurrency/plots}"
  LOG_ROOT="${LOG_ROOT_BASE:-fyp/dash_dataset/synthetic/${PROTOCOL}}"
  mkdir -p "$OUT_DIR"

  DATASET="$DATASET_ORIG"

  # Expand family shorthand into individual dataset names
  FAMILY_DATASETS=()
  if [[ "$DATASET" =~ ^(incast|a2a)_(mono|heavytail_burst|pareto_alpha|heavytail_sigma|heavytail_temp)_n$ ]]; then
    case "$DATASET" in
      *_mono_n)            prefix="${BASH_REMATCH[1]}_mono_" ;;
      *_heavytail_burst_n) prefix="${BASH_REMATCH[1]}_heavytail_burst_" ;;
      *_pareto_alpha_n)    prefix="${BASH_REMATCH[1]}_pareto_alpha_" ;;
      *_heavytail_sigma_n) prefix="${BASH_REMATCH[1]}_heavytail_sigma_" ;;
      *_heavytail_temp_n)  prefix="${BASH_REMATCH[1]}_heavytail_temp_" ;;
    esac
    while IFS= read -r log; do
      [[ -n "$log" ]] || continue
      name="$(basename "$log")"; name="${name#log_}"; name="${name%.txt}"
      FAMILY_DATASETS+=("$name")
    done < <(find "$LOG_ROOT" -maxdepth 1 -type f -name "log_${prefix}*.txt" | sort)
    DATASET=""
  fi

  cmd=(python3 fyp/dash_scripts/plot_flow_concurrency.py --logs-dir "$LOG_ROOT" --out-dir "$OUT_DIR" --prefix "$PREFIX" --max-records "$MAX_RECORDS" --max-plot-intervals "$MAX_PLOT_INTERVALS")
  if [[ -n "$DATASET" ]]; then
    cmd+=(--dataset "$DATASET")
  fi
  for ds in "${FAMILY_DATASETS[@]+"${FAMILY_DATASETS[@]}"}"; do
    cmd+=(--dataset "$ds")
  done
  if [[ "$LOW_TEMP_LOCALITY" == "1" ]]; then
    cmd+=(--low-temp-locality)
  fi
  if [[ "$WITH_CONCURRENCY" == "1" ]]; then
    cmd+=(--with-concurrency)
  fi
  if [[ "$PLOT_CONCURRENCY" == "1" ]]; then
    cmd+=(--plot-concurrency)
  fi

  "${cmd[@]}"

  echo "Done [$PROTOCOL]. Synthetic temporal locality plots are under: $OUT_DIR"
done
