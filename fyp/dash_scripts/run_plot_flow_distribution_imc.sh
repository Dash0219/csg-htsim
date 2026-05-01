#!/usr/bin/env bash
set -euo pipefail

print_usage() {
  cat <<'EOF'
Usage:
  bash fyp/dash_scripts/run_plot_flow_distribution_imc.sh [options]

Options:
  -d, --dataset NAME         Limit plotting to one IMC dataset (uni1 or uni2)
  -o, --out-base DIR         Output base directory (default: fyp/dash_results/imc)
  --prefix NAME          Output filename prefix base (default: sink_flow_size)
      --cols N               Subplot grid columns (default: 4)
      --max-sinks N          Maximum sink files to include per dataset (0 means all)
      --sort-by MODE         rows | flows | name (default: rows)
  -h, --help                 Show this help
EOF
}

DATASET="${DATASET:-}"
OUT_BASE="${OUT_BASE:-fyp/dash_results/imc}"
PREFIX="${PREFIX:-}"
COLS="${COLS:-4}"
MAX_SINKS="${MAX_SINKS:-0}"
SORT_BY="${SORT_BY:-rows}"

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
    --prefix)
      [[ $# -ge 2 ]] || { echo "ERROR: --prefix requires a value" >&2; exit 1; }
      PREFIX="$2"
      shift 2
      ;;
    --cols)
      [[ $# -ge 2 ]] || { echo "ERROR: --cols requires a value" >&2; exit 1; }
      COLS="$2"
      shift 2
      ;;
    --max-sinks)
      [[ $# -ge 2 ]] || { echo "ERROR: --max-sinks requires a value" >&2; exit 1; }
      MAX_SINKS="$2"
      shift 2
      ;;
    --sort-by)
      [[ $# -ge 2 ]] || { echo "ERROR: --sort-by requires a value" >&2; exit 1; }
      SORT_BY="$2"
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

  split_dir="fyp/dash_dataset/imc/${ds}/${ds}_sinks_top8_prefix16"
  if [[ ! -d "$split_dir" ]]; then
    echo "Skipping missing split dir: $split_dir"
    continue
  fi

  out_dir="$OUT_BASE/$ds/flow_size/plots"
  mkdir -p "$out_dir"

  echo "== plotting IMC flow size for $ds =="
  ds_prefix="${PREFIX:-${ds}_top8}"
  python3 fyp/dash_scripts/plot_sink_flow_distributions.py \
    --split-dir "$split_dir" \
    --out-dir "$out_dir" \
    --prefix "$ds_prefix" \
    --cols "$COLS" \
    --max-sinks "$MAX_SINKS" \
    --sort-by "$SORT_BY"
  count=$((count + 1))
done

echo "Done. Plotted flow sizes for $count IMC dataset(s) into $OUT_BASE/{uni1,uni2}/flow_size/plots"
