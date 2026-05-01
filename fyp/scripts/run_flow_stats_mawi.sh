#!/usr/bin/env bash
set -euo pipefail

print_usage() {
  cat <<'EOF'
Usage:
  bash fyp/scripts/run_flow_stats_mawi.sh [options]

Options:
  -s, --split-dir DIR        Input split directory (default: fyp/dataset/mawi/mawi_sinks_top8_prefix16)
  -o, --out-dir DIR          Output directory (default: fyp/results/mawi/flow_stats)
      --top N                Top N flows in report output (default: 20)
  -h, --help                 Show this help

Environment variables:
  TOP_N                      Backward-compatible fallback for --top
EOF
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

SPLIT_DIR="${SPLIT_DIR:-fyp/dataset/mawi/mawi_sinks_top8_prefix16}"
OUT_DIR="${OUT_DIR:-fyp/results/mawi/flow_stats}"
TOP_N="${TOP_N:-20}"

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
    --top)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --top requires a value" >&2
        exit 1
      fi
      TOP_N="$2"
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

mkdir -p "$OUT_DIR"

if [[ ! -d "$SPLIT_DIR" ]]; then
  echo "ERROR: split dir not found: $SPLIT_DIR" >&2
  exit 1
fi

logs=()
for sink_file in "$SPLIT_DIR"/*.txt; do
  [[ -f "$sink_file" ]] || continue
  sink_base="$(basename "$sink_file" .txt)"

  report_txt="$OUT_DIR/${sink_base}_flow_stats.txt"
  report_csv="$OUT_DIR/${sink_base}_flow_stats.csv"
  python3 fyp/scripts/flow_stats.py "$sink_file" --top "$TOP_N" --concurrency --csv "$report_csv" > "$report_txt"
  logs+=("$sink_file")
done

if [[ ${#logs[@]} -gt 0 ]]; then
  python3 fyp/scripts/flow_stats.py "${logs[@]}" --top "$TOP_N" --concurrency --csv "$OUT_DIR/mawi_top8_all_flow_stats.csv" > "$OUT_DIR/mawi_top8_all_flow_stats.txt"
fi

echo "Done. MAWI flow stats outputs are under: $OUT_DIR"
