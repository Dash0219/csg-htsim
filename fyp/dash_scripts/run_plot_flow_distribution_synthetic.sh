#!/usr/bin/env bash
set -euo pipefail

print_usage() {
  cat <<'EOF'
Usage:
  bash fyp/dash_scripts/run_plot_flow_distribution_synthetic.sh [options]

Options:
  -d, --dataset NAME        Only plot one synthetic dataset (repeatable)
  -p, --protocol NAME       Transport protocol: ndp or hpcc (default: ndp)
  -o, --out-dir DIR         Output directory (default: fyp/dash_results/synthetic/<protocol>/flow_size/plots)
      --prefix NAME         Output filename prefix root (default: flow_size)
  -h, --help                Show this help
EOF
}

declare -a DATASETS=()
PROTOCOL="${PROTOCOL:-ndp}"
OUT_DIR="${OUT_DIR:-}"
PREFIX="${PREFIX:-flow_size}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -d|--dataset)
      [[ $# -ge 2 ]] || { echo "ERROR: --dataset requires a value" >&2; exit 1; }
      DATASETS+=("$2")
      shift 2
      ;;
    -p|--protocol)
      [[ $# -ge 2 ]] || { echo "ERROR: --protocol requires a value" >&2; exit 1; }
      PROTOCOL="$2"
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

if [[ "$PROTOCOL" != "ndp" && "$PROTOCOL" != "hpcc" ]]; then
  echo "ERROR: --protocol must be ndp or hpcc" >&2
  exit 1
fi

OUT_DIR="${OUT_DIR:-fyp/dash_results/synthetic/${PROTOCOL}/flow_size/plots}"
LOG_ROOT="fyp/dash_dataset/synthetic/${PROTOCOL}"
mkdir -p "$OUT_DIR"

normalize_dataset_alias() {
  local name="$1"
  case "$name" in
    incast)
      echo "incast_mono"
      ;;
    a2a)
      echo "a2a_mono"
      ;;
    *)
      echo "$name"
      ;;
  esac
}

collect_all_datasets() {
  find "$LOG_ROOT" -maxdepth 1 -type f -name 'log_*.txt' \
    | sed -E 's#^.*/log_##; s#\.txt$##' \
    | sort -u
}

emit_group_plot() {
  local group="$1"
  shift
  local datasets=("$@")
  if [[ ${#datasets[@]} -eq 0 ]]; then
    echo "Skipping ${group}: no matching datasets found"
    return
  fi

  echo "== plotting flow-size group: ${group} (${#datasets[@]} datasets) =="
  local cmd=(python3 fyp/dash_scripts/plot_flow_distributions.py --logs-dir "$LOG_ROOT" --out-dir "$OUT_DIR" --prefix "${PREFIX}_${group}")
  local ds
  for ds in "${datasets[@]}"; do
    cmd+=(--dataset "$ds")
  done
  "${cmd[@]}"
}

if [[ ${#DATASETS[@]} -gt 0 ]]; then
  normalized=()
  for ds in "${DATASETS[@]}"; do
    normalized+=("$(normalize_dataset_alias "$ds")")
  done
  emit_group_plot "custom" "${normalized[@]}"
  echo "Done. Synthetic flow size plots are under: $OUT_DIR"
  exit 0
fi

all_ds=()
while IFS= read -r ds; do
  [[ -n "$ds" ]] || continue
  all_ds+=("$ds")
done < <(collect_all_datasets)

test_run=()
for ds in \
  incast_mono a2a_mono \
  incast_bimodal a2a_bimodal \
  incast_pareto a2a_pareto \
  incast_heavytail a2a_heavytail \
  incast_exponential_skewed a2a_exponential_skewed; do
  if printf '%s\n' "${all_ds[@]}" | grep -qx "$ds"; then
    test_run+=("$ds")
  fi
done

burst=()
alpha=()
temp=()
mono=()
sigma=()

for ds in "${all_ds[@]}"; do
  if [[ "$ds" =~ ^(incast|a2a)_heavytail_burst_[0-9]+$ ]]; then
    burst+=("$ds")
  elif [[ "$ds" =~ ^(incast|a2a)_pareto_alpha_[0-9]+(p[0-9]+)?$ ]]; then
    alpha+=("$ds")
  elif [[ "$ds" =~ ^(incast|a2a)_pareto_temp_[0-9]+$ ]]; then
    temp+=("$ds")
  elif [[ "$ds" =~ ^(incast|a2a)_mono_[0-9]+$ ]]; then
    mono+=("$ds")
  elif [[ "$ds" =~ ^(incast|a2a)_heavytail_sigma_[0-9]+(p[0-9]+)?$ ]]; then
    sigma+=("$ds")
  fi
done

if [[ ${#burst[@]} -gt 0 ]]; then
  burst_sorted=()
  while IFS= read -r ds; do
    [[ -n "$ds" ]] || continue
    burst_sorted+=("$ds")
  done < <(printf '%s\n' "${burst[@]}" | sort -V)
  burst=("${burst_sorted[@]}")
fi
if [[ ${#alpha[@]} -gt 0 ]]; then
  alpha_sorted=()
  while IFS= read -r ds; do
    [[ -n "$ds" ]] || continue
    alpha_sorted+=("$ds")
  done < <(printf '%s\n' "${alpha[@]}" | sort -V)
  alpha=("${alpha_sorted[@]}")
fi
if [[ ${#temp[@]} -gt 0 ]]; then
  temp_sorted=()
  while IFS= read -r ds; do
    [[ -n "$ds" ]] || continue
    temp_sorted+=("$ds")
  done < <(printf '%s\n' "${temp[@]}" | sort -V)
  temp=("${temp_sorted[@]}")
fi
if [[ ${#mono[@]} -gt 0 ]]; then
  mono_sorted=()
  while IFS= read -r ds; do
    [[ -n "$ds" ]] || continue
    mono_sorted+=("$ds")
  done < <(printf '%s\n' "${mono[@]}" | sort -V)
  mono=("${mono_sorted[@]}")
fi
if [[ ${#sigma[@]} -gt 0 ]]; then
  sigma_sorted=()
  while IFS= read -r ds; do
    [[ -n "$ds" ]] || continue
    sigma_sorted+=("$ds")
  done < <(printf '%s\n' "${sigma[@]}" | sort -V)
  sigma=("${sigma_sorted[@]}")
fi

emit_group_plot "test_run" "${test_run[@]}"
emit_group_plot "sweep_burst" "${burst[@]}"
emit_group_plot "sweep_alpha" "${alpha[@]}"
emit_group_plot "sweep_temp" "${temp[@]}"
emit_group_plot "sweep_mono" "${mono[@]}"
emit_group_plot "sweep_sigma" "${sigma[@]}"

echo "Done. Synthetic flow size plots are under: $OUT_DIR"
