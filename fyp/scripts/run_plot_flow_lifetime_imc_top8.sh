#!/usr/bin/env bash
set -euo pipefail

print_usage() {
  cat <<'EOF'
Usage:
  bash fyp/scripts/run_plot_flow_lifetime_imc_top8.sh [options]

Options:
  -d, --dataset NAME         Limit plotting to one IMC dataset (uni1 or uni2)
  -o, --out-base DIR         Output base directory (default: fyp/results/imc)
  -p, --prefix NAME          Output filename prefix (default: flow_lifetime_imc_top8)
      --max-records N        Limit records parsed by plotter (default: 2000000, 0 means all)
      --bins N               Histogram bin count (default: 50)
  -h, --help                 Show this help

Environment variables:
  MAX_RECORDS                Backward-compatible fallback for --max-records
EOF
}

DATASET="${DATASET:-}"
OUT_BASE="${OUT_BASE:-fyp/results/imc}"
PREFIX="${PREFIX:-flow_lifetime_imc_top8}"
MAX_RECORDS="${MAX_RECORDS:-2000000}"
BINS="${BINS:-50}"

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

  split_dir="fyp/dataset/imc/${ds}/${ds}_sinks_top8_prefix16"
  if [[ ! -d "$split_dir" ]]; then
    echo "Skipping missing split dir: $split_dir"
    continue
  fi

  out_dir="$OUT_BASE/$ds/flow_lifetime/plots"
  mkdir -p "$out_dir"

  for sink_file in "$split_dir"/*.txt "$split_dir"/*.log; do
    [[ -f "$sink_file" ]] || continue
    python3 fyp/scripts/plot_flow_lifetimes.py \
      "$sink_file" \
      --out-dir "$out_dir" \
      --prefix "${PREFIX}_${ds}" \
      --max-records "$MAX_RECORDS" \
      --bins "$BINS"
    count=$((count + 1))
  done
done

echo "Done. Plotted flow lifetimes for $count IMC top-8 split files into $OUT_BASE/{uni1,uni2}/flow_lifetime/plots"
