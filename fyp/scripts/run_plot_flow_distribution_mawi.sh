#!/usr/bin/env bash
set -euo pipefail

print_usage() {
  cat <<'EOF'
Usage:
  bash fyp/scripts/run_plot_flow_distribution_mawi.sh [options]

Options:
  -s, --split-dir DIR        Input split directory (default: fyp/dataset/mawi/mawi_sinks_top8_prefix16)
  -o, --out-dir DIR          Output directory (default: fyp/results/mawi/flow_size/plots)
      --prefix NAME          Output filename prefix (default: sink_flow_size_mawi_top8)
      --cols N               Subplot grid columns (default: 4)
      --max-sinks N          Maximum sink files to include (0 means all)
      --sort-by MODE         rows | flows | name (default: rows)
  -h, --help                 Show this help
EOF
}

SPLIT_DIR="${SPLIT_DIR:-fyp/dataset/mawi/mawi_sinks_top8_prefix16}"
OUT_DIR="${OUT_DIR:-fyp/results/mawi/flow_size/plots}"
PREFIX="${PREFIX:-mawi_top8}"
COLS="${COLS:-4}"
MAX_SINKS="${MAX_SINKS:-0}"
SORT_BY="${SORT_BY:-rows}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -s|--split-dir)
      [[ $# -ge 2 ]] || { echo "ERROR: --split-dir requires a value" >&2; exit 1; }
      SPLIT_DIR="$2"
      shift 2
      ;;
    -o|--out-dir)
      [[ $# -ge 2 ]] || { echo "ERROR: --out-dir requires a value" >&2; exit 1; }
      OUT_DIR="$2"
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

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -d "$SPLIT_DIR" ]]; then
  echo "ERROR: split dir not found: $SPLIT_DIR" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"

python3 fyp/scripts/plot_sink_flow_distributions.py \
  --split-dir "$SPLIT_DIR" \
  --out-dir "$OUT_DIR" \
  --prefix "$PREFIX" \
  --cols "$COLS" \
  --max-sinks "$MAX_SINKS" \
  --sort-by "$SORT_BY"

echo "Done. MAWI flow size plots are under: $OUT_DIR"
