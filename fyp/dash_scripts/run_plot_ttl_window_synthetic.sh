#!/usr/bin/env bash
set -euo pipefail

print_usage() {
  cat <<'EOF'
Usage:
  bash fyp/dash_scripts/run_plot_ttl_window_synthetic.sh [options]

Options:
  -d, --dataset NAME        Only plot one synthetic dataset (e.g., a2a_pareto)
  -p, --protocol NAME       Transport protocol: ndp or hpcc (default: ndp)
  -o, --out-dir DIR         Output directory (default: fyp/dash_results/synthetic/<protocol>/ttl_window/plots)
      --prefix NAME         Output filename prefix (default: ttl_window)
      --max-records N       Limit parsed records (default: 0 means all)
      --bins N              Histogram bin count (default: 50)
      --key-level MODE      flow | source | switch (default: flow)
      --event-mode MODE     all | congestion (default: all)
      --qs-threshold N      Queue threshold for congestion mode (default: 50000)
      --merge-inputs        Merge selected inputs into one aggregate output
      --merge-label NAME    Label for merged output
  -h, --help                Show this help
EOF
}

DATASET="${DATASET:-}"
LOW_TEMP_LOCALITY="${LOW_TEMP_LOCALITY:-0}"
LOW_TEMP_SUFFIX="${LOW_TEMP_SUFFIX:-low_temp_locality}"
PROTOCOL="${PROTOCOL:-ndp}"
OUT_DIR="${OUT_DIR:-}"
PREFIX="${PREFIX:-ttl_window}"
MAX_RECORDS="${MAX_RECORDS:-0}"
BINS="${BINS:-50}"
KEY_LEVEL="${KEY_LEVEL:-flow}"
EVENT_MODE="${EVENT_MODE:-all}"
QS_THRESHOLD="${QS_THRESHOLD:-50000}"
MERGE_INPUTS=0
MERGE_LABEL="${MERGE_LABEL:-}"

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
    --bins)
      [[ $# -ge 2 ]] || { echo "ERROR: --bins requires a value" >&2; exit 1; }
      BINS="$2"
      shift 2
      ;;
    --key-level)
      [[ $# -ge 2 ]] || { echo "ERROR: --key-level requires a value" >&2; exit 1; }
      KEY_LEVEL="$2"
      shift 2
      ;;
    --event-mode)
      [[ $# -ge 2 ]] || { echo "ERROR: --event-mode requires a value" >&2; exit 1; }
      EVENT_MODE="$2"
      shift 2
      ;;
    --qs-threshold)
      [[ $# -ge 2 ]] || { echo "ERROR: --qs-threshold requires a value" >&2; exit 1; }
      QS_THRESHOLD="$2"
      shift 2
      ;;
    --merge-inputs)
      MERGE_INPUTS=1
      shift
      ;;
    --merge-label)
      [[ $# -ge 2 ]] || { echo "ERROR: --merge-label requires a value" >&2; exit 1; }
      MERGE_LABEL="$2"
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

OUT_DIR="${OUT_DIR:-fyp/dash_results/synthetic/${PROTOCOL}/ttl_window/plots}"
LOG_ROOT="fyp/dash_dataset/synthetic/${PROTOCOL}"
mkdir -p "$OUT_DIR"

cmd=(python3 fyp/dash_scripts/plot_ttl_windows.py --logs-dir "$LOG_ROOT" --out-dir "$OUT_DIR" --prefix "$PREFIX" --max-records "$MAX_RECORDS" --bins "$BINS" --key-level "$KEY_LEVEL" --event-mode "$EVENT_MODE" --qs-threshold "$QS_THRESHOLD")
if [[ -n "$DATASET" ]]; then
  cmd+=(--dataset "$DATASET")
fi
if [[ "$LOW_TEMP_LOCALITY" == "1" ]]; then
  cmd+=(--low-temp-locality)
fi
if [[ "$MERGE_INPUTS" == "1" ]]; then
  cmd+=(--merge-inputs)
  if [[ -n "$MERGE_LABEL" ]]; then
    cmd+=(--merge-label "$MERGE_LABEL")
  fi
fi

"${cmd[@]}"

echo "Done. Synthetic TTL-window plots are under: $OUT_DIR"
