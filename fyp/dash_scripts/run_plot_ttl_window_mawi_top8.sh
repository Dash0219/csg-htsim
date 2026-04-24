#!/usr/bin/env bash
set -euo pipefail

print_usage() {
  cat <<'EOF'
Usage:
  bash fyp/dash_scripts/run_plot_ttl_window_mawi_top8.sh [options]

Options:
  -s, --split-dir DIR        Input split directory (default: fyp/dash_dataset/mawi/mawi_sinks_top8_prefix16)
  -o, --out-dir DIR          Output directory (default: fyp/dash_results/mawi/ttl_window/plots)
  -p, --prefix NAME          Output filename prefix (default: ttl_window_mawi_top8)
      --max-records N        Limit records parsed by plotter (default: 0 means all)
      --bins N               Histogram bin count (default: 50)
      --key-level MODE       flow | source | switch (default: source)
      --event-mode MODE      all | congestion (default: all)
      --qs-threshold N       Queue threshold for congestion mode (default: 50000)
      --per-sink             Plot one output per sink split file
  -h, --help                 Show this help
EOF
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

SPLIT_DIR="${SPLIT_DIR:-fyp/dash_dataset/mawi/mawi_sinks_top8_prefix16}"
OUT_DIR="${OUT_DIR:-fyp/dash_results/mawi/ttl_window/plots}"
PREFIX="${PREFIX:-ttl_window_mawi_top8}"
MAX_RECORDS="${MAX_RECORDS:-0}"
BINS="${BINS:-50}"
KEY_LEVEL="${KEY_LEVEL:-source}"
EVENT_MODE="${EVENT_MODE:-all}"
QS_THRESHOLD="${QS_THRESHOLD:-50000}"
PER_SINK=0

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
    --per-sink)
      PER_SINK=1
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

files=()
for sink_file in "$SPLIT_DIR"/*.txt; do
  [[ -f "$sink_file" ]] || continue
  files+=("$sink_file")
done

if [[ ${#files[@]} -eq 0 ]]; then
  echo "ERROR: no split files found in: $SPLIT_DIR" >&2
  exit 1
fi

count=0
if [[ "$PER_SINK" == "1" ]]; then
  for sink_file in "${files[@]}"; do
    python3 fyp/dash_scripts/plot_ttl_windows.py "$sink_file" \
      --out-dir "$OUT_DIR" \
      --prefix "$PREFIX" \
      --max-records "$MAX_RECORDS" \
      --bins "$BINS" \
      --key-level "$KEY_LEVEL" \
      --event-mode "$EVENT_MODE" \
      --qs-threshold "$QS_THRESHOLD"
    count=$((count + 1))
  done
else
  python3 fyp/dash_scripts/plot_ttl_windows.py "${files[@]}" \
    --merge-inputs \
    --merge-label "mawi_top8" \
    --out-dir "$OUT_DIR" \
    --prefix "$PREFIX" \
    --max-records "$MAX_RECORDS" \
    --bins "$BINS" \
    --key-level "$KEY_LEVEL" \
    --event-mode "$EVENT_MODE" \
    --qs-threshold "$QS_THRESHOLD"
  count=1
fi

echo "Done. Plotted $count MAWI TTL-window output(s) to $OUT_DIR"
