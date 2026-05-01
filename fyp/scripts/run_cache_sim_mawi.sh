#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

SPLIT_DIR="${1:-fyp/dataset/mawi/mawi_sinks_top8_prefix16}"
OUT_DIR="${2:-fyp/results/mawi/cache_sim/source_seen}"
CSV_OUT="$OUT_DIR/results_mawi_source_seen_top8.csv"
CAPACITY_DIR="${OUT_DIR}/capacity"
CAPACITY_PLOTS_DIR="${CAPACITY_DIR}/plots/mawi"
CAPACITY_CSV="${CAPACITY_DIR}/results_mawi_source_seen_top8_capacity.csv"
CAPACITY_PLOT_CAPACITIES="${CAPACITY_PLOT_CAPACITIES:-}"
CAPACITY_PLOT_MIN_CAPACITY="${CAPACITY_PLOT_MIN_CAPACITY:-512}"

mkdir -p "$OUT_DIR" "$CAPACITY_DIR" "$CAPACITY_PLOTS_DIR"

if [[ ! -d "$SPLIT_DIR" ]]; then
  echo "ERROR: split dir not found: $SPLIT_DIR" >&2
  exit 1
fi

echo "== MAWI source-seen sweep =="
if ! (
  PYTHONUNBUFFERED=1 python3 fyp/scripts/cache_sim_source_seen_int.py "$SPLIT_DIR" \
    --pattern '*.txt' --sweep --fast --quiet-table --csv-per-split --csv "$CSV_OUT" --capacity-csv "$CAPACITY_CSV" \
    2>&1 | tee "$OUT_DIR/run_mawi_source_seen_top8.out"
); then
  echo "ERROR: MAWI source-seen sweep failed. Last log lines:" >&2
  tail -n 40 "$OUT_DIR/run_mawi_source_seen_top8.out" >&2 || true
  exit 1
fi

plot_cmd=(python3 fyp/scripts/plot_cache_capacity.py "$CAPACITY_CSV" --out-dir "$CAPACITY_PLOTS_DIR" --prefix "mawi_source_seen_capacity" --min-capacity "$CAPACITY_PLOT_MIN_CAPACITY")
if [[ -n "$CAPACITY_PLOT_CAPACITIES" ]]; then
  plot_cmd+=(--capacities "$CAPACITY_PLOT_CAPACITIES")
fi
"${plot_cmd[@]}"

echo "Wrote: $CSV_OUT"
echo "Done. MAWI source-seen CSVs under: $OUT_DIR"
