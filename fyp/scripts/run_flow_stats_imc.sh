#!/usr/bin/env bash
set -euo pipefail

print_usage() {
  cat <<'EOF'
Usage:
  bash fyp/scripts/run_flow_stats_imc.sh [options]

Options:
  -d, --dataset NAME         Limit processing to one IMC dataset (uni1 or uni2)
  -o, --out-base DIR         Output base directory (default: fyp/results/imc)
      --top N                Top N flows in report output (default: 20)
  -h, --help                 Show this help

Environment variables:
  TOP_N                      Backward-compatible fallback for --top
EOF
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

DATASET="${DATASET:-}"
OUT_BASE="${OUT_BASE:-fyp/results/imc}"
TOP_N="${TOP_N:-20}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -d|--dataset)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --dataset requires a value" >&2
        exit 1
      fi
      DATASET="$2"
      shift 2
      ;;
    -o|--out-base)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --out-base requires a value" >&2
        exit 1
      fi
      OUT_BASE="$2"
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

if [[ -n "$DATASET" && "$DATASET" != "uni1" && "$DATASET" != "uni2" ]]; then
  echo "ERROR: --dataset must be uni1 or uni2" >&2
  exit 1
fi

mkdir -p "$OUT_BASE"

for ds in uni1 uni2; do
  if [[ -n "$DATASET" && "$ds" != "$DATASET" ]]; then
    continue
  fi
  out_dir="$OUT_BASE/$ds/flow_stats"
  mkdir -p "$out_dir"
  logs=()
  split_dir="fyp/dataset/imc/${ds}/${ds}_sinks_top8_prefix16"
  if [[ ! -d "$split_dir" ]]; then
    echo "Skipping missing split dir: $split_dir"
    continue
  fi

  for sink_file in "$split_dir"/*.txt "$split_dir"/*.log; do
    [[ -f "$sink_file" ]] || continue
    sink_base="$(basename "$sink_file")"
    sink_base="${sink_base%.*}"

    report_txt="$out_dir/${sink_base}_flow_stats.txt"
    report_csv="$out_dir/${sink_base}_flow_stats.csv"
    python3 fyp/scripts/flow_stats.py "$sink_file" --top "$TOP_N" --concurrency --csv "$report_csv" > "$report_txt"
    logs+=("$sink_file")
  done

  if [[ ${#logs[@]} -gt 0 ]]; then
    python3 fyp/scripts/flow_stats.py "${logs[@]}" --top "$TOP_N" --concurrency --csv "$out_dir/${ds}_all_flow_stats.csv" > "$out_dir/${ds}_all_flow_stats.txt"
  fi
done

echo "Done. IMC flow stats outputs are under: $OUT_BASE/{uni1,uni2}/flow_stats"
