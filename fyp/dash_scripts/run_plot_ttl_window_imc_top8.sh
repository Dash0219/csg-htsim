#!/usr/bin/env bash
set -euo pipefail

print_usage() {
  cat <<'EOF'
Usage:
  bash fyp/dash_scripts/run_plot_ttl_window_imc_top8.sh [options]

Options:
  -d, --dataset NAME         Limit plotting to one IMC dataset (uni1 or uni2)
  -o, --out-base DIR         Output base directory (default: fyp/dash_results/imc)
  -p, --prefix NAME          Output filename prefix (default: ttl_window_imc_top8)
      --max-records N        Limit records parsed by plotter (default: 0 means all)
      --bins N               Histogram bin count (default: 50)
      --key-level MODE       flow | source | switch (default: source)
      --event-mode MODE      all | congestion (default: all)
      --qs-threshold N       Queue threshold for congestion mode (default: 50000)
      --per-sink             Plot one output per sink split file
  -h, --help                 Show this help
EOF
}

DATASET="${DATASET:-}"
OUT_BASE="${OUT_BASE:-fyp/dash_results/imc}"
PREFIX="${PREFIX:-ttl_window_imc_top8}"
MAX_RECORDS="${MAX_RECORDS:-0}"
BINS="${BINS:-50}"
KEY_LEVEL="${KEY_LEVEL:-source}"
EVENT_MODE="${EVENT_MODE:-all}"
QS_THRESHOLD="${QS_THRESHOLD:-50000}"
PER_SINK=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -d|--dataset)
      [[ $# -ge 2 ]] || { echo "ERROR: --dataset requires a value" >&2; exit 1; }
      DATASET="$2"
      shift 2
      ;;
    -o|--out-base)
      [[ $# -ge 2 ]] || { echo "ERROR: --out-base requires a value" >&2; exit 1; }
      OUT_BASE="$2"
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

if [[ -n "$DATASET" && "$DATASET" != "uni1" && "$DATASET" != "uni2" ]]; then
  echo "ERROR: --dataset must be uni1 or uni2" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

count=0
for ds in uni1 uni2; do
  if [[ -n "$DATASET" && "$ds" != "$DATASET" ]]; then
    continue
  fi

  split_dir="fyp/dash_dataset/imc/${ds}/${ds}_sinks_top8_prefix16"
  out_dir="$OUT_BASE/$ds/ttl_window/plots"
  mkdir -p "$out_dir"

  if [[ ! -d "$split_dir" ]]; then
    echo "Skipping missing split dir: $split_dir"
    continue
  fi

  files=()
  for sink_file in "$split_dir"/*.txt "$split_dir"/*.log; do
    [[ -f "$sink_file" ]] || continue
    files+=("$sink_file")
  done

  if [[ ${#files[@]} -eq 0 ]]; then
    echo "Skipping empty split dir: $split_dir"
    continue
  fi

  if [[ "$PER_SINK" == "1" ]]; then
    for sink_file in "${files[@]}"; do
      python3 fyp/dash_scripts/plot_ttl_windows.py "$sink_file" \
        --out-dir "$out_dir" \
        --prefix "${PREFIX}_${ds}" \
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
      --merge-label "${ds}_top8" \
      --out-dir "$out_dir" \
      --prefix "${PREFIX}_${ds}" \
      --max-records "$MAX_RECORDS" \
      --bins "$BINS" \
      --key-level "$KEY_LEVEL" \
      --event-mode "$EVENT_MODE" \
      --qs-threshold "$QS_THRESHOLD"
    count=$((count + 1))
  fi
done

echo "Done. Plotted $count IMC TTL-window output(s) to $OUT_BASE/{uni1,uni2}/ttl_window/plots"
