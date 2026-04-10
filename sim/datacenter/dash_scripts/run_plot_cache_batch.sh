#!/usr/bin/env bash
set -euo pipefail

print_usage() {
  cat <<'EOF'
Usage:
  bash dash_scripts/run_plot_cache_batch.sh [OUT_BASE] [options]

Options:
  -d, --dataset NAME        Only plot one synthetic dataset stem for synthetic CSVs
  -l, --low-temp-locality   Only plot low-temp-locality synthetic datasets
      --max-concurrency N   Optional cache-capacity marker for max concurrent flows
      --unique-flows N      Optional cache-capacity marker for unique flows
      --switch-budget N     Optional practical switch cache-size marker
      --hide-limit-labels   Draw limit lines without text labels
      --disable-policy NAME Hide one policy in plots (repeatable)
      --include-policy NAME Keep only selected policies (repeatable)
      --hide-redundant-pairs Hide near-duplicate policies in final figures
  -h, --help           Show this help
EOF
}

DATASET="${DATASET:-}"
LOW_TEMP_LOCALITY="${LOW_TEMP_LOCALITY:-0}"
LOW_TEMP_SUFFIX="${LOW_TEMP_SUFFIX:-low_temp_locality}"
MAX_CONCURRENCY="${MAX_CONCURRENCY:-0}"
UNIQUE_FLOWS="${UNIQUE_FLOWS:-0}"
SWITCH_BUDGET="${SWITCH_BUDGET:-0}"
HIDE_LIMIT_LABELS=0
HIDE_REDUNDANT_PAIRS=0
declare -a DISABLE_POLICIES=()
declare -a INCLUDE_POLICIES=()

OUT_BASE=""
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
    --max-concurrency)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --max-concurrency requires a value" >&2
        exit 1
      fi
      MAX_CONCURRENCY="$2"
      shift 2
      ;;
    --unique-flows)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --unique-flows requires a value" >&2
        exit 1
      fi
      UNIQUE_FLOWS="$2"
      shift 2
      ;;
    --switch-budget)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --switch-budget requires a value" >&2
        exit 1
      fi
      SWITCH_BUDGET="$2"
      shift 2
      ;;
    --hide-limit-labels)
      HIDE_LIMIT_LABELS=1
      shift
      ;;
    --disable-policy)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --disable-policy requires a value" >&2
        exit 1
      fi
      DISABLE_POLICIES+=("$2")
      shift 2
      ;;
    --include-policy)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --include-policy requires a value" >&2
        exit 1
      fi
      INCLUDE_POLICIES+=("$2")
      shift 2
      ;;
    --hide-redundant-pairs)
      HIDE_REDUNDANT_PAIRS=1
      shift
      ;;
    -h|--help)
      print_usage
      exit 0
      ;;
    *)
      if [[ -z "$OUT_BASE" ]]; then
        OUT_BASE="$1"
      else
        echo "ERROR: unexpected argument: $1" >&2
        exit 1
      fi
      shift
      ;;
  esac
done

if [[ "$LOW_TEMP_LOCALITY" != "0" && "$LOW_TEMP_LOCALITY" != "1" ]]; then
  echo "ERROR: LOW_TEMP_LOCALITY must be 0 or 1" >&2
  exit 1
fi

if [[ "$LOW_TEMP_LOCALITY" == "1" && -n "$DATASET" && "$DATASET" != *"_${LOW_TEMP_SUFFIX}" ]]; then
  DATASET="${DATASET}_${LOW_TEMP_SUFFIX}"
fi

case "$DATASET" in
  incast)
    DATASET="incast_mono"
    ;;
  a2a)
    DATASET="a2a_mono"
    ;;
  incast_${LOW_TEMP_SUFFIX})
    DATASET="incast_mono_${LOW_TEMP_SUFFIX}"
    ;;
  a2a_${LOW_TEMP_SUFFIX})
    DATASET="a2a_mono_${LOW_TEMP_SUFFIX}"
    ;;
esac

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

OUT_BASE="${OUT_BASE:-dash_results}"
mkdir -p "$OUT_BASE"

EXTRA_ARGS=()
if [[ -n "$MAX_CONCURRENCY" && "$MAX_CONCURRENCY" != "0" ]]; then
  EXTRA_ARGS+=(--max-concurrency "$MAX_CONCURRENCY")
fi
if [[ -n "$UNIQUE_FLOWS" && "$UNIQUE_FLOWS" != "0" ]]; then
  EXTRA_ARGS+=(--unique-flows "$UNIQUE_FLOWS")
fi
if [[ -n "$SWITCH_BUDGET" && "$SWITCH_BUDGET" != "0" ]]; then
  EXTRA_ARGS+=(--switch-budget "$SWITCH_BUDGET")
fi
if [[ "$HIDE_LIMIT_LABELS" == "1" ]]; then
  EXTRA_ARGS+=(--hide-limit-labels)
fi
if [[ "$HIDE_REDUNDANT_PAIRS" == "1" ]]; then
  EXTRA_ARGS+=(--hide-redundant-pairs)
fi
join_csv() {
  local IFS=','
  echo "$*"
}
if [[ ${#DISABLE_POLICIES[@]} -gt 0 ]]; then
  EXTRA_ARGS+=(--exclude-policies "$(join_csv "${DISABLE_POLICIES[@]}")")
fi
if [[ ${#INCLUDE_POLICIES[@]} -gt 0 ]]; then
  EXTRA_ARGS+=(--include-policies "$(join_csv "${INCLUDE_POLICIES[@]}")")
fi

OUT_SYN_ROUTE="$OUT_BASE/synthetic/cache_sim/route_changes/plots"
OUT_SYN_SOURCE="$OUT_BASE/synthetic/cache_sim/source_seen/plots"
OUT_UNIV1="$OUT_BASE/imc/univ1/cache_sim/source_seen/plots"
OUT_UNIV2="$OUT_BASE/imc/univ2/cache_sim/source_seen/plots"
mkdir -p "$OUT_SYN_ROUTE" "$OUT_SYN_SOURCE" "$OUT_UNIV1" "$OUT_UNIV2"

count=0
for csv in dash_results/synthetic/cache_sim/route_changes/results_synthetic_*.csv; do
  [[ -f "$csv" ]] || continue
  stem="$(basename "$csv" .csv)"
  dataset_name="${stem#results_synthetic_}"
  if [[ "$LOW_TEMP_LOCALITY" == "1" && "$dataset_name" != *"_${LOW_TEMP_SUFFIX}" ]]; then
    continue
  fi
  if [[ "$LOW_TEMP_LOCALITY" == "0" && "$dataset_name" == *"_${LOW_TEMP_SUFFIX}" ]]; then
    continue
  fi
  if [[ -n "$DATASET" && "$stem" != "results_synthetic_${DATASET}" ]]; then
    continue
  fi
  echo "== plotting synthetic/$stem =="
  python3 dash_scripts/plot_cache.py "$csv" --out "$OUT_SYN_ROUTE" --prefix "$stem" "${EXTRA_ARGS[@]}"
  count=$((count + 1))
done

for csv in dash_results/synthetic/cache_sim/route_change/results_synthetic_*.csv; do
  [[ -f "$csv" ]] || continue
  stem="$(basename "$csv" .csv)"
  dataset_name="${stem#results_synthetic_}"
  if [[ "$LOW_TEMP_LOCALITY" == "1" && "$dataset_name" != *"_${LOW_TEMP_SUFFIX}" ]]; then
    continue
  fi
  if [[ "$LOW_TEMP_LOCALITY" == "0" && "$dataset_name" == *"_${LOW_TEMP_SUFFIX}" ]]; then
    continue
  fi
  if [[ -n "$DATASET" && "$dataset_name" != "$DATASET" ]]; then
    continue
  fi
  echo "== plotting synthetic/$stem =="
  python3 dash_scripts/plot_cache.py "$csv" --out "$OUT_SYN_ROUTE" --prefix "$stem" "${EXTRA_ARGS[@]}"
  count=$((count + 1))
done

for csv in dash_results/synthetic/cache_sim/source_seen/results_synthetic_source_seen_*.csv; do
  [[ -f "$csv" ]] || continue
  stem="$(basename "$csv" .csv)"
  dataset_name="${stem#results_synthetic_source_seen_}"
  if [[ "$LOW_TEMP_LOCALITY" == "1" && "$dataset_name" != *"_${LOW_TEMP_SUFFIX}" ]]; then
    continue
  fi
  if [[ "$LOW_TEMP_LOCALITY" == "0" && "$dataset_name" == *"_${LOW_TEMP_SUFFIX}" ]]; then
    continue
  fi
  if [[ -n "$DATASET" && "$dataset_name" != "$DATASET" ]]; then
    continue
  fi
  echo "== plotting synthetic/$stem =="
  python3 dash_scripts/plot_cache.py "$csv" --out "$OUT_SYN_SOURCE" --prefix "$stem" "${EXTRA_ARGS[@]}"
  count=$((count + 1))
done

for csv in dash_results/imc/univ1/cache_sim/source_seen/results_univ1_source_seen_top8_splits/*.csv; do
  [[ -f "$csv" ]] || continue
  stem="$(basename "$csv" .csv)"
  echo "== plotting univ1/$stem =="
  python3 dash_scripts/plot_cache.py "$csv" --out "$OUT_UNIV1" --prefix "$stem" "${EXTRA_ARGS[@]}"
  count=$((count + 1))
done

for csv in dash_results/imc/univ2/cache_sim/source_seen/results_univ2_source_seen_top8_splits/*.csv; do
  [[ -f "$csv" ]] || continue
  stem="$(basename "$csv" .csv)"
  echo "== plotting univ2/$stem =="
  python3 dash_scripts/plot_cache.py "$csv" --out "$OUT_UNIV2" --prefix "$stem" "${EXTRA_ARGS[@]}"
  count=$((count + 1))
done

echo "Done. Plotted $count CSV file(s) to configured dataset plot directories under $OUT_BASE"
