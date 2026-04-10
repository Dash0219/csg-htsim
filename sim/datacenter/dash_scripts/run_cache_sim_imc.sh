#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

datasets=(univ1 univ2)
for ds in "${datasets[@]}"; do
  split_dir="dash_dataset/imc/${ds}/${ds}_sinks_top8_prefix16"
  out_dir="dash_results/imc/${ds}/cache_sim/source_seen"
  csv_out="${out_dir}/results_${ds}_source_seen_top8.csv"
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
  python3 dash_scripts/cache_sim_source_seen_int.py "$split_dir" \
    --pattern "$split_pattern" --sweep --csv-per-split --csv "$csv_out" \
    > "${out_dir}/run_${ds}_source_seen_top8.out" 2>&1
  echo "Wrote: $csv_out"
done

echo "Done. IMC source-seen CSVs under dash_results/imc/{univ1,univ2}/cache_sim/source_seen"
