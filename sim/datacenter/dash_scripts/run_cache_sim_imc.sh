#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Keep very large splits bounded; univ2_sink_244.157.0.0_16 can be an extreme outlier.
# 6.5M keeps runtime close to the largest "normal" split (~6.3M) with some headroom.
IMC_MAX_PACKETS_PER_SPLIT="${IMC_MAX_PACKETS_PER_SPLIT:-7000000}"

datasets=(univ1 univ2)
for ds in "${datasets[@]}"; do
  split_dir="dash_dataset/imc/${ds}/${ds}_sinks_top8_prefix16"
  out_dir="dash_results/imc/${ds}/cache_sim/source_seen"
  csv_out="${out_dir}/results_${ds}_source_seen_top8.csv"
  run_log="${out_dir}/run_${ds}_source_seen_top8.out"
  mkdir -p "$out_dir"

  if [[ ! -d "$split_dir" ]]; then
    echo "Skipping missing split dir: $split_dir"
    continue
  fi

  split_pattern='*.txt'
  if ! compgen -G "$split_dir/*.txt" > /dev/null; then
    split_pattern='*.log'
  fi

  echo "== IMC source-seen sweep: $ds =="
  echo "   max packets per split: ${IMC_MAX_PACKETS_PER_SPLIT}"
  if ! (
    PYTHONUNBUFFERED=1 python3 dash_scripts/cache_sim_source_seen_int.py "$split_dir" \
      --pattern "$split_pattern" --sweep --fast --quiet-table \
      --max-records "$IMC_MAX_PACKETS_PER_SPLIT" --csv-per-split --csv "$csv_out" \
      2>&1 | tee "$run_log"
  ); then
    echo "ERROR: IMC source-seen sweep failed for ${ds}. Last log lines:" >&2
    tail -n 40 "$run_log" >&2 || true
    exit 1
  fi
  echo "Wrote: $csv_out"
done

echo "Done. IMC source-seen CSVs under dash_results/imc/{univ1,univ2}/cache_sim/source_seen"
