#!/usr/bin/env bash
set -euo pipefail

print_usage() {
  cat <<'EOF'
Usage:
  bash fyp/scripts/run_plot_flow_distribution_synthetic.sh [options]

Options:
  -d, --dataset NAME        Only plot one synthetic dataset (repeatable), or a family shorthand:
                              incast_mono_n / a2a_mono_n
                              incast_heavytail_burst_n / a2a_heavytail_burst_n
                              incast_pareto_alpha_n / a2a_pareto_alpha_n
                              incast_heavytail_sigma_n / a2a_heavytail_sigma_n
                              incast_heavytail_temp_n / a2a_heavytail_temp_n
  -p, --protocol NAME       Transport protocol: ndp, hpcc, or tcp (default: all three)
  -o, --out-dir DIR         Output directory (default: fyp/results/synthetic/<protocol>/flow_size/plots)
      --prefix NAME         Output filename prefix root (default: flow_size)
  -h, --help                Show this help
EOF
}

declare -a DATASETS=()
PROTOCOLS="${PROTOCOL:-ndp hpcc tcp}"
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
      PROTOCOLS="$2"
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

for proto in $PROTOCOLS; do
  if [[ "$proto" != "ndp" && "$proto" != "hpcc" && "$proto" != "tcp" ]]; then
    echo "ERROR: --protocol must be ndp, hpcc, or tcp (got: $proto)" >&2
    exit 1
  fi
done

OUT_DIR_BASE="${OUT_DIR:-}"
LOG_ROOT_BASE="${LOG_ROOT:-}"
DATASETS_ORIG=("${DATASETS[@]+"${DATASETS[@]}"}")

normalize_dataset_alias() {
  local name="$1"
  case "$name" in
    incast) echo "incast_mono" ;;
    a2a)    echo "a2a_mono" ;;
    *)      echo "$name" ;;
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
  local cmd=(python3 fyp/scripts/plot_flow_distributions.py --logs-dir "$LOG_ROOT" --out-dir "$OUT_DIR" --prefix "${PREFIX}_${group}")
  local ds
  for ds in "${datasets[@]}"; do
    cmd+=(--dataset "$ds")
  done
  "${cmd[@]}"
}

expand_family_shorthand() {
  local shorthand="$1"
  local prefix=""
  if [[ "$shorthand" =~ ^(incast|a2a)_mono_n$ ]]; then
    prefix="${BASH_REMATCH[1]}_mono_"
  elif [[ "$shorthand" =~ ^(incast|a2a)_heavytail_burst_n$ ]]; then
    prefix="${BASH_REMATCH[1]}_heavytail_burst_"
  elif [[ "$shorthand" =~ ^(incast|a2a)_pareto_alpha_n$ ]]; then
    prefix="${BASH_REMATCH[1]}_pareto_alpha_"
  elif [[ "$shorthand" =~ ^(incast|a2a)_heavytail_sigma_n$ ]]; then
    prefix="${BASH_REMATCH[1]}_heavytail_sigma_"
  elif [[ "$shorthand" =~ ^(incast|a2a)_heavytail_temp_n$ ]]; then
    prefix="${BASH_REMATCH[1]}_heavytail_temp_"
  else
    echo "$shorthand"
    return
  fi
  while IFS= read -r log; do
    [[ -n "$log" ]] || continue
    local name
    name="$(basename "$log")"; name="${name#log_}"; name="${name%.txt}"
    echo "$name"
  done < <(find "$LOG_ROOT" -maxdepth 1 -type f -name "log_${prefix}*.txt" | sort)
}

for PROTOCOL in $PROTOCOLS; do
  echo "=== Protocol: $PROTOCOL ==="

  OUT_DIR="${OUT_DIR_BASE:-fyp/results/synthetic/${PROTOCOL}/flow_size/plots}"
  LOG_ROOT="${LOG_ROOT_BASE:-fyp/dataset/synthetic/${PROTOCOL}}"
  mkdir -p "$OUT_DIR"

  DATASETS=("${DATASETS_ORIG[@]+"${DATASETS_ORIG[@]}"}")

  if [[ ${#DATASETS[@]} -gt 0 ]]; then
    normalized=()
    for ds in "${DATASETS[@]}"; do
      ds="$(normalize_dataset_alias "$ds")"
      while IFS= read -r expanded; do
        [[ -n "$expanded" ]] || continue
        normalized+=("$expanded")
      done < <(expand_family_shorthand "$ds")
    done
    emit_group_plot "custom" "${normalized[@]+"${normalized[@]}"}"
    echo "Done [$PROTOCOL]. Synthetic flow size plots are under: $OUT_DIR"
    continue
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
    elif [[ "$ds" =~ ^(incast|a2a)_(pareto|heavytail)_temp_[0-9]+(p[0-9]+)?$ ]]; then
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

  emit_group_plot "test_run" "${test_run[@]+"${test_run[@]}"}"
  emit_group_plot "sweep_burst" "${burst[@]+"${burst[@]}"}"
  emit_group_plot "sweep_alpha" "${alpha[@]+"${alpha[@]}"}"
  emit_group_plot "sweep_temp" "${temp[@]+"${temp[@]}"}"
  emit_group_plot "sweep_mono" "${mono[@]+"${mono[@]}"}"
  emit_group_plot "sweep_sigma" "${sigma[@]+"${sigma[@]}"}"

  echo "Done [$PROTOCOL]. Synthetic flow size plots are under: $OUT_DIR"
done
