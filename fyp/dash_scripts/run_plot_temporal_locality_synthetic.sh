#!/usr/bin/env bash
set -euo pipefail

print_usage() {
  cat <<'EOF'
Usage:
  bash fyp/dash_scripts/run_plot_temporal_locality_synthetic.sh [options]

Options:
  -d, --dataset NAME        Only plot one synthetic dataset (e.g., a2a_pareto)
  -p, --protocol NAME       Transport protocol: ndp or hpcc (default: ndp)
  -o, --out-dir DIR         Output directory (default: fyp/dash_results/synthetic/<protocol>/temporal_locality/plots)
      --prefix NAME         Output filename prefix (default: temporal_locality)
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
PROTOCOL="${PROTOCOL:-ndp}"
OUT_DIR="${OUT_DIR:-}"
PREFIX="${PREFIX:-temporal_locality}"
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
      PROTOCOL="$2"
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

if [[ "$PROTOCOL" != "ndp" && "$PROTOCOL" != "hpcc" ]]; then
  echo "ERROR: --protocol must be ndp or hpcc" >&2
  exit 1
fi

OUT_DIR="${OUT_DIR:-fyp/dash_results/synthetic/${PROTOCOL}/temporal_locality/plots}"
LOG_ROOT="fyp/dash_dataset/synthetic/${PROTOCOL}"
mkdir -p "$OUT_DIR"

cmd=(python3 fyp/dash_scripts/plot_temporal_locality.py --logs-dir "$LOG_ROOT" --out-dir "$OUT_DIR" --prefix "$PREFIX" --max-records "$MAX_RECORDS" --max-plot-intervals "$MAX_PLOT_INTERVALS")
if [[ -n "$DATASET" ]]; then
  cmd+=(--dataset "$DATASET")
fi
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

echo "Done. Synthetic temporal locality plots are under: $OUT_DIR"
