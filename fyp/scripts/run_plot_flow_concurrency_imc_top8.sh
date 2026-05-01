#!/usr/bin/env bash
set -euo pipefail

print_usage() {
  cat <<'EOF'
Usage:
  bash fyp/scripts/run_plot_flow_concurrency_imc_top8.sh [options]

Options:
  -d, --dataset NAME         Limit plotting to one IMC dataset (uni1 or uni2)
  -o, --out-base DIR         Output base directory (default: fyp/results/imc)
  -p, --prefix NAME          Output filename prefix (default: flow_concurrency_imc_top8)
      --max-records N        Limit records parsed by plotter (default: 2000000, 0 means all)
      --max-plot-intervals N Cap intervals rendered per sink plot (default: 300000, 0 means all)
      --with-concurrency     Overlay concurrency on temporal plots
      --plot-concurrency     Emit separate concurrency PNG
  -h, --help                 Show this help

Environment variables:
  MAX_RECORDS                 Backward-compatible fallback for --max-records
  MAX_PLOT_INTERVALS          Backward-compatible fallback for --max-plot-intervals
  WITH_CONCURRENCY            Backward-compatible fallback for --with-concurrency (1/0, default 0)
  PLOT_CONCURRENCY            Backward-compatible fallback for --plot-concurrency (1/0, default 0)
EOF
}

DATASET="${DATASET:-}"
OUT_BASE="${OUT_BASE:-fyp/results/imc}"
PREFIX="${PREFIX:-flow_concurrency_imc_top8}"
MAX_RECORDS="${MAX_RECORDS:-2000000}"
MAX_PLOT_INTERVALS="${MAX_PLOT_INTERVALS:-300000}"
WITH_CONCURRENCY="${WITH_CONCURRENCY:-0}"
PLOT_CONCURRENCY="${PLOT_CONCURRENCY:-0}"

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
    -p|--prefix)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --prefix requires a value" >&2
        exit 1
      fi
      PREFIX="$2"
      shift 2
      ;;
    --max-records)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --max-records requires a value" >&2
        exit 1
      fi
      MAX_RECORDS="$2"
      shift 2
      ;;
    --max-plot-intervals)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --max-plot-intervals requires a value" >&2
        exit 1
      fi
      MAX_PLOT_INTERVALS="$2"
      shift 2
      ;;
    --with-concurrency)
      WITH_CONCURRENCY=1
      shift
      ;;
    --plot-concurrency)
      PLOT_CONCURRENCY=1
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

mkdir -p "$OUT_BASE"

count=0
for ds in uni1 uni2; do
  if [[ -n "$DATASET" && "$ds" != "$DATASET" ]]; then
    continue
  fi
  out_dir="$OUT_BASE/$ds/flow_concurrency/plots"
  mkdir -p "$out_dir"
  split_dir="fyp/dataset/imc/${ds}/${ds}_sinks_top8_prefix16"
  if [[ ! -d "$split_dir" ]]; then
    echo "Skipping missing split dir: $split_dir"
    continue
  fi

  for sink_file in "$split_dir"/*.txt "$split_dir"/*.log; do
    [[ -f "$sink_file" ]] || continue
    plot_cmd=(python3 fyp/scripts/plot_flow_concurrency.py "$sink_file" --out-dir "$out_dir" --prefix "${PREFIX}_${ds}" --max-records "$MAX_RECORDS" --max-plot-intervals "$MAX_PLOT_INTERVALS")
    if [[ "$WITH_CONCURRENCY" == "1" ]]; then
      plot_cmd+=(--with-concurrency)
    fi
    if [[ "$PLOT_CONCURRENCY" == "1" ]]; then
      plot_cmd+=(--plot-concurrency)
    fi
    "${plot_cmd[@]}"

    count=$((count + 1))
  done
done

echo "Done. Plotted temporal locality for $count IMC top-8 split files into $OUT_BASE/{uni1,uni2}/flow_concurrency/plots"
