#!/usr/bin/env bash
set -euo pipefail

print_usage() {
  cat <<'EOF'
Usage:
  bash fyp/scripts/run_plot_flow_concurrency_mawi_top8.sh [options]

Options:
  -s, --split-dir DIR        Input split directory (default: fyp/dataset/mawi/mawi_sinks_top8_prefix16)
  -o, --out-dir DIR          Output directory (default: fyp/results/mawi/flow_concurrency/plots)
  -p, --prefix NAME          Output filename prefix (default: flow_concurrency_mawi_top8)
      --max-records N        Limit records parsed by plotter (default: 2000000, 0 means all)
      --max-plot-intervals N Cap intervals rendered per sink plot (default: 300000, 0 means all)
      --with-concurrency     Overlay concurrency on temporal plots
      --plot-concurrency     Emit separate concurrency PNG
  -h, --help                 Show this help

Environment variables:
  MAX_RECORDS                 Backward-compatible fallback for --max-records
  MAX_PLOT_INTERVALS          Backward-compatible fallback for --max-plot-intervals
  WITH_CONCURRENCY            Backward-compatible fallback for --with-concurrency (1/0, default 0)
  PLOT_CONCURRENCY            Backward-compatible fallback for --plot-concurrency (1/0, default 0)
EOF
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

SPLIT_DIR="${SPLIT_DIR:-fyp/dataset/mawi/mawi_sinks_top8_prefix16}"
OUT_DIR="${OUT_DIR:-fyp/results/mawi/flow_concurrency/plots}"
PREFIX="${PREFIX:-flow_concurrency_mawi_top8}"

MAX_RECORDS="${MAX_RECORDS:-2000000}"
MAX_PLOT_INTERVALS="${MAX_PLOT_INTERVALS:-300000}"
WITH_CONCURRENCY="${WITH_CONCURRENCY:-0}"
PLOT_CONCURRENCY="${PLOT_CONCURRENCY:-0}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -s|--split-dir)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --split-dir requires a value" >&2
        exit 1
      fi
      SPLIT_DIR="$2"
      shift 2
      ;;
    -o|--out-dir)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --out-dir requires a value" >&2
        exit 1
      fi
      OUT_DIR="$2"
      shift 2
      ;;
    -p|--prefix)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --prefix requires a value" >&2
        exit 1
      fi
      PREFIX="$2"
      shift 2
      ;;
    --max-records)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --max-records requires a value" >&2
        exit 1
      fi
      MAX_RECORDS="$2"
      shift 2
      ;;
    --max-plot-intervals)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --max-plot-intervals requires a value" >&2
        exit 1
      fi
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

mkdir -p "$OUT_DIR"

if [[ ! -d "$SPLIT_DIR" ]]; then
  echo "ERROR: split dir not found: $SPLIT_DIR" >&2
  exit 1
fi

count=0
for sink_file in "$SPLIT_DIR"/*.txt; do
  [[ -f "$sink_file" ]] || continue
  plot_cmd=(python3 fyp/scripts/plot_flow_concurrency.py "$sink_file" --out-dir "$OUT_DIR" --prefix "$PREFIX" --max-records "$MAX_RECORDS" --max-plot-intervals "$MAX_PLOT_INTERVALS")
  if [[ "$WITH_CONCURRENCY" == "1" ]]; then
    plot_cmd+=(--with-concurrency)
  fi
  if [[ "$PLOT_CONCURRENCY" == "1" ]]; then
    plot_cmd+=(--plot-concurrency)
  fi
  "${plot_cmd[@]}"
  count=$((count + 1))
done

echo "Done. Plotted temporal locality for $count MAWI split files into $OUT_DIR"
