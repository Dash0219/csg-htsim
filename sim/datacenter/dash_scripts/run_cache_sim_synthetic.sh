#!/usr/bin/env bash
set -euo pipefail

print_usage() {
  cat <<'EOF'
Usage:
  bash dash_scripts/run_cache_sim_synthetic.sh [options]

Options:
  -d, --dataset NAME        Process one synthetic dataset family (example: a2a_pareto)
  -l, --low-temp-locality   Process only low-temp-locality datasets
  -h, --help           Show this help

Environment variables:
  LOW_TEMP_LOCALITY    Equivalent to --low-temp-locality (0/1)
  DATASET              Equivalent to --dataset
  TARGET_PATTERN       Deprecated legacy alias for DATASET
EOF
}

DATASET="${DATASET:-}"
TARGET_PATTERN="${TARGET_PATTERN:-}"
LOW_TEMP_LOCALITY="${LOW_TEMP_LOCALITY:-0}"

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
    -l|--low-temp-locality)
      LOW_TEMP_LOCALITY=1
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

if [[ -z "$DATASET" && -n "$TARGET_PATTERN" ]]; then
  DATASET="$TARGET_PATTERN"
  echo "WARN: TARGET_PATTERN is deprecated; use --dataset (or DATASET) instead." >&2
elif [[ -n "$DATASET" && -n "$TARGET_PATTERN" && "$DATASET" != "$TARGET_PATTERN" ]]; then
  echo "ERROR: DATASET ($DATASET) and TARGET_PATTERN ($TARGET_PATTERN) disagree" >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

OUT_DIR="dash_results/synthetic/cache_sim/route_changes"
LOW_TEMP_SUFFIX="${LOW_TEMP_SUFFIX:-low_temp_locality}"

is_low_dataset_name() {
  local name="$1"
  [[ "$name" == *"_${LOW_TEMP_SUFFIX}" ]]
}

if [[ "$LOW_TEMP_LOCALITY" != "0" && "$LOW_TEMP_LOCALITY" != "1" ]]; then
  echo "ERROR: LOW_TEMP_LOCALITY must be 0 or 1" >&2
  exit 1
fi

if [[ "$LOW_TEMP_LOCALITY" == "1" && -n "$DATASET" ]] && ! is_low_dataset_name "$DATASET"; then
  DATASET="${DATASET}_${LOW_TEMP_SUFFIX}"
fi

if [[ "$LOW_TEMP_LOCALITY" == "0" && -n "$DATASET" ]] && is_low_dataset_name "$DATASET"; then
  LOW_TEMP_LOCALITY=1
fi

normalize_dataset_alias() {
  local name="$1"
  case "$name" in
    incast)
      echo "incast_mono"
      ;;
    a2a)
      echo "a2a_mono"
      ;;
    incast_${LOW_TEMP_SUFFIX})
      echo "incast_mono_${LOW_TEMP_SUFFIX}"
      ;;
    a2a_${LOW_TEMP_SUFFIX})
      echo "a2a_mono_${LOW_TEMP_SUFFIX}"
      ;;
    *)
      echo "$name"
      ;;
  esac
}

if [[ -n "$DATASET" ]]; then
  DATASET="$(normalize_dataset_alias "$DATASET")"
fi

mkdir -p "$OUT_DIR"

normal_patterns=(
  incast_mono
  a2a_mono
  incast_bimodal
  a2a_bimodal
  incast_pareto
  a2a_pareto
  incast_pareto_heavy
  a2a_pareto_heavy
  incast_lognormal_skewed
  a2a_lognormal_skewed
  incast_exponential_skewed
  a2a_exponential_skewed
)

low_patterns=(
  incast_mono_${LOW_TEMP_SUFFIX}
  a2a_mono_${LOW_TEMP_SUFFIX}
  incast_bimodal_${LOW_TEMP_SUFFIX}
  a2a_bimodal_${LOW_TEMP_SUFFIX}
  incast_pareto_${LOW_TEMP_SUFFIX}
  a2a_pareto_${LOW_TEMP_SUFFIX}
  incast_pareto_heavy_${LOW_TEMP_SUFFIX}
  a2a_pareto_heavy_${LOW_TEMP_SUFFIX}
  incast_lognormal_skewed_${LOW_TEMP_SUFFIX}
  a2a_lognormal_skewed_${LOW_TEMP_SUFFIX}
  incast_exponential_skewed_${LOW_TEMP_SUFFIX}
  a2a_exponential_skewed_${LOW_TEMP_SUFFIX}
)

patterns=("${normal_patterns[@]}")
if [[ "$LOW_TEMP_LOCALITY" == "1" ]]; then
  patterns=("${low_patterns[@]}")
fi

if [[ -n "$DATASET" ]]; then
  found=0
  for p in "${patterns[@]}"; do
    if [[ "$p" == "$DATASET" ]]; then
      found=1
      break
    fi
  done
  if [[ "$found" != "1" ]]; then
    echo "ERROR: unknown dataset '$DATASET'" >&2
    exit 1
  fi
fi

for p in "${patterns[@]}"; do
  if [[ -n "$DATASET" && "$p" != "$DATASET" ]]; then
    continue
  fi
  log="dash_dataset/synthetic/log_${p}.txt"
  csv="$OUT_DIR/results_synthetic_${p}.csv"
  if [[ ! -f "$log" ]]; then
    echo "Skipping missing input: $log"
    continue
  fi
  echo "== cache_sim sweep: $p =="
  python3 dash_scripts/cache_sim.py "$log" --sweep --csv "$csv"
done

echo "Done. Route-change CSV outputs are under: $OUT_DIR"
