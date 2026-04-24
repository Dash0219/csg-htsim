#!/usr/bin/env bash
set -euo pipefail

print_usage() {
  cat <<'EOF'
Usage:
  bash fyp/dash_scripts/run_plot_flow_lifetime_mawi_top8.sh [options]

Options:
  -s, --split-dir DIR        Input split directory (default: fyp/dash_dataset/mawi/mawi_sinks_top8_prefix16)
  -o, --out-dir DIR          Output directory (default: fyp/dash_results/mawi/flow_lifetime/plots)
  -p, --prefix NAME          Output filename prefix (default: flow_lifetime_mawi_top8)
      --max-records N        Limit records parsed by plotter (default: 2000000, 0 means all)
      --bins N               Histogram bin count (default: 50)
  -h, --help                 Show this help

Environment variables:
  MAX_RECORDS                Backward-compatible fallback for --max-records
EOF
}

SPLIT_DIR="${SPLIT_DIR:-fyp/dash_dataset/mawi/mawi_sinks_top8_prefix16}"
OUT_DIR="${OUT_DIR:-fyp/dash_results/mawi/flow_lifetime/plots}"
PREFIX="${PREFIX:-flow_lifetime_mawi_top8}"
MAX_RECORDS="${MAX_RECORDS:-2000000}"
BINS="${BINS:-50}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -s|--split-dir)
      [[ $# -ge 2 ]] || { echo "ERROR: --split-dir requires a value" >&2; exit 1; }
      SPLIT_DIR="$2"
      shift 2
      ;;
    -o|--out-dir)
      [[ $# -ge 2 ]] || { echo "ERROR: --out-dir requires a value" >&2; exit 1; }
      OUT_DIR="$2"
      shift 2
      ;;
    -p|--prefix)
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

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -d "$SPLIT_DIR" ]]; then
  echo "ERROR: split dir not found: $SPLIT_DIR" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"

count=0
for sink_file in "$SPLIT_DIR"/*.txt; do
  [[ -f "$sink_file" ]] || continue
  python3 fyp/dash_scripts/plot_flow_lifetimes.py \
    "$sink_file" \
    --out-dir "$OUT_DIR" \
    --prefix "$PREFIX" \
    --max-records "$MAX_RECORDS" \
    --bins "$BINS"
  count=$((count + 1))
done

echo "Done. Plotted flow lifetimes for $count MAWI top-8 split files into $OUT_DIR"
