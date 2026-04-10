#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SPLIT_DIR="${1:-dash_dataset/mawi/mawi_sinks_top8_prefix16}"
OUT_DIR="${2:-dash_results/mawi/cache_sim/source_seen}"
CSV_OUT="$OUT_DIR/results_mawi_source_seen_top8.csv"

mkdir -p "$OUT_DIR"

if [[ ! -d "$SPLIT_DIR" ]]; then
  echo "ERROR: split dir not found: $SPLIT_DIR" >&2
  exit 1
fi

echo "== MAWI source-seen sweep =="
python3 dash_scripts/cache_sim_source_seen_int.py "$SPLIT_DIR" \
  --pattern '*.txt' --sweep --csv-per-split --csv "$CSV_OUT" \
  > "$OUT_DIR/run_mawi_source_seen_top8.out" 2>&1

echo "Wrote: $CSV_OUT"
echo "Done. MAWI source-seen CSVs under: $OUT_DIR"
