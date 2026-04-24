#!/usr/bin/env bash
set -euo pipefail

print_usage() {
  cat <<'EOF'
Usage:
  bash fyp/dash_scripts/run_plot_cache_imc.sh [OUT_BASE] [options]

Options:
  -d, --dataset NAME        Limit plotting to one IMC dataset (univ1 or univ2)
  -n, --scale-to-infinite   Scale y-axis using observed infinite/data range
      --scale-factor X      Headroom multiplier with --scale-to-infinite (default: 1.25)
      --max-concurrency N   Override concurrency marker capacity (default: inferred from flow stats)
      --no-max-concurrency  Disable concurrency marker
      --unique-flows N      Override unique-flow marker capacity (default: inferred from flow stats)
      --no-unique-flows     Disable unique-flow marker
      --switch-budget N     Optional practical switch cache-size marker
      --hide-limit-labels   Draw limit lines without text labels
      --disable-policy NAME Hide one policy in plots (repeatable)
      --include-policy NAME Keep only selected policies (repeatable)
      --hide-redundant-pairs Hide near-duplicate policies in final figures
  -h, --help           Show this help
EOF
}

DATASET="${DATASET:-}"
SCALE_TO_INFINITE="${SCALE_TO_INFINITE:-0}"
SCALE_FACTOR="${SCALE_FACTOR:-1.25}"
MAX_CONCURRENCY="${MAX_CONCURRENCY:-0}"
UNIQUE_FLOWS="${UNIQUE_FLOWS:-0}"
USE_MAX_CONCURRENCY=1
USE_UNIQUE_FLOWS=1
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
    -h|--help)
      print_usage
      exit 0
      ;;
    -n|--scale-to-infinite)
      SCALE_TO_INFINITE=1
      shift
      ;;
    --scale-factor)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --scale-factor requires a value" >&2
        exit 1
      fi
      SCALE_FACTOR="$2"
      shift 2
      ;;
    --max-concurrency)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --max-concurrency requires a value" >&2
        exit 1
      fi
      MAX_CONCURRENCY="$2"
      shift 2
      ;;
    --no-max-concurrency)
      USE_MAX_CONCURRENCY=0
      shift
      ;;
    --unique-flows)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --unique-flows requires a value" >&2
        exit 1
      fi
      UNIQUE_FLOWS="$2"
      shift 2
      ;;
    --no-unique-flows)
      USE_UNIQUE_FLOWS=0
      shift
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

if [[ -n "$DATASET" && "$DATASET" != "univ1" && "$DATASET" != "univ2" ]]; then
  echo "ERROR: --dataset must be univ1 or univ2" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

OUT_BASE="${OUT_BASE:-fyp/dash_results/imc}"
mkdir -p "$OUT_BASE"

PLOT_ARGS=()
if [[ "$SCALE_TO_INFINITE" == "1" ]]; then
  PLOT_ARGS+=(--scale-to-infinite --scale-factor "$SCALE_FACTOR")
fi
if [[ "$HIDE_LIMIT_LABELS" == "1" ]]; then
  PLOT_ARGS+=(--hide-limit-labels)
fi
if [[ "$HIDE_REDUNDANT_PAIRS" == "1" ]]; then
  PLOT_ARGS+=(--hide-redundant-pairs)
fi

join_csv() {
  local IFS=','
  echo "$*"
}

if [[ ${#DISABLE_POLICIES[@]} -gt 0 ]]; then
  PLOT_ARGS+=(--exclude-policies "$(join_csv "${DISABLE_POLICIES[@]}")")
fi
if [[ ${#INCLUDE_POLICIES[@]} -gt 0 ]]; then
  PLOT_ARGS+=(--include-policies "$(join_csv "${INCLUDE_POLICIES[@]}")")
fi

stats_file_for_stem() {
  local ds="$1"
  local stem="$2"
  local stats_dir="fyp/dash_results/imc/$ds/flow_stats"
  if [[ ! -d "$stats_dir" ]]; then
    return
  fi

  if [[ "$stem" =~ ^split_[0-9]+_(.+)$ ]]; then
    local sink_base="${BASH_REMATCH[1]}"
    local sink_stats="$stats_dir/${sink_base}_flow_stats.txt"
    if [[ -f "$sink_stats" ]]; then
      echo "$sink_stats"
      return
    fi
  fi

  if [[ "$stem" == "results_${ds}_source_seen_top8" ]]; then
    local total_stats="$stats_dir/${ds}_all_flow_stats.txt"
    if [[ -f "$total_stats" ]]; then
      echo "$total_stats"
      return
    fi
  fi
}

infer_max_concurrency_for_stem() {
  local ds="$1"
  local stem="$2"
  local stats_file
  stats_file="$(stats_file_for_stem "$ds" "$stem")"
  if [[ -z "$stats_file" || ! -f "$stats_file" ]]; then
    return
  fi
  grep -E 'Peak concurrency:|Max peak concurrency' "$stats_file" 2>/dev/null \
    | sed -E 's/.*: *([0-9][0-9,]*).*/\1/' \
    | tr -d ',' \
    | awk 'max<$1{max=$1} END{if(max>0) print max}'
}

infer_unique_flows_for_stem() {
  local ds="$1"
  local stem="$2"
  local stats_file
  stats_file="$(stats_file_for_stem "$ds" "$stem")"
  if [[ -z "$stats_file" || ! -f "$stats_file" ]]; then
    return
  fi
  grep -E 'Unique flows:' "$stats_file" 2>/dev/null \
    | sed -E 's/.*: *([0-9][0-9,]*).*/\1/' \
    | tr -d ',' \
    | awk 'max<$1{max=$1} END{if(max>0) print max}'
}

run_plot() {
  local csv="$1"
  local out="$2"
  local stem="$3"
  local concurrency="$4"
  local unique_flows="$5"
  local args=(--out "$out" --prefix "$stem")
  if [[ ${#PLOT_ARGS[@]} -gt 0 ]]; then
    args+=("${PLOT_ARGS[@]}")
  fi
  if [[ -n "$concurrency" && "$concurrency" != "0" ]]; then
    args+=(--max-concurrency "$concurrency")
  fi
  if [[ -n "$unique_flows" && "$unique_flows" != "0" ]]; then
    args+=(--unique-flows "$unique_flows")
  fi
  if [[ -n "$SWITCH_BUDGET" && "$SWITCH_BUDGET" != "0" ]]; then
    args+=(--switch-budget "$SWITCH_BUDGET")
  fi
  python3 fyp/dash_scripts/plot_cache.py "$csv" "${args[@]}"
}

count=0
for ds in univ1 univ2; do
  if [[ -n "$DATASET" && "$ds" != "$DATASET" ]]; then
    continue
  fi
  out_dir="$OUT_BASE/$ds/cache_sim/source_seen/plots"
  mkdir -p "$out_dir"
  ds_max_concurrency="$MAX_CONCURRENCY"
  if [[ "$USE_MAX_CONCURRENCY" == "0" ]]; then
    ds_max_concurrency="0"
  fi
  ds_unique_flows="$UNIQUE_FLOWS"
  if [[ "$USE_UNIQUE_FLOWS" == "0" ]]; then
    ds_unique_flows="0"
  fi
  split_dir="fyp/dash_results/imc/$ds/cache_sim/source_seen/results_${ds}_source_seen_top8_splits"
  if [[ -d "$split_dir" ]]; then
    for csv in "$split_dir"/*.csv; do
      [[ -f "$csv" ]] || continue
      stem="$(basename "$csv" .csv)"
      csv_max_concurrency="$ds_max_concurrency"
      if [[ "$USE_MAX_CONCURRENCY" != "0" && ( -z "$csv_max_concurrency" || "$csv_max_concurrency" == "0" ) ]]; then
        inferred_split=$(infer_max_concurrency_for_stem "$ds" "$stem")
        if [[ -n "$inferred_split" ]]; then
          csv_max_concurrency="$inferred_split"
        fi
      fi
      csv_unique_flows="$ds_unique_flows"
      if [[ "$USE_UNIQUE_FLOWS" != "0" && ( -z "$csv_unique_flows" || "$csv_unique_flows" == "0" ) ]]; then
        inferred_unique_split=$(infer_unique_flows_for_stem "$ds" "$stem")
        if [[ -n "$inferred_unique_split" ]]; then
          csv_unique_flows="$inferred_unique_split"
        fi
      fi
      echo "== plotting $ds/$stem =="
      echo "   markers: max_concurrency=${csv_max_concurrency:-0} unique_flows=${csv_unique_flows:-0}"
      run_plot "$csv" "$out_dir" "$stem" "$csv_max_concurrency" "$csv_unique_flows"
      count=$((count + 1))
    done
  fi

  total_csv="fyp/dash_results/imc/$ds/cache_sim/source_seen/results_${ds}_source_seen_top8.csv"
  if [[ -f "$total_csv" ]]; then
    stem="$(basename "$total_csv" .csv)"
    csv_max_concurrency="$ds_max_concurrency"
    if [[ "$USE_MAX_CONCURRENCY" != "0" && ( -z "$csv_max_concurrency" || "$csv_max_concurrency" == "0" ) ]]; then
      inferred_total=$(infer_max_concurrency_for_stem "$ds" "$stem")
      if [[ -n "$inferred_total" ]]; then
        csv_max_concurrency="$inferred_total"
      fi
    fi
    csv_unique_flows="$ds_unique_flows"
    if [[ "$USE_UNIQUE_FLOWS" != "0" && ( -z "$csv_unique_flows" || "$csv_unique_flows" == "0" ) ]]; then
      inferred_unique_total=$(infer_unique_flows_for_stem "$ds" "$stem")
      if [[ -n "$inferred_unique_total" ]]; then
        csv_unique_flows="$inferred_unique_total"
      fi
    fi
    echo "== plotting $ds/$stem =="
    echo "   markers: max_concurrency=${csv_max_concurrency:-0} unique_flows=${csv_unique_flows:-0}"
    run_plot "$total_csv" "$out_dir" "$stem" "$csv_max_concurrency" "$csv_unique_flows"
    count=$((count + 1))
  fi
done

echo "Done. Plotted $count IMC split CSV file(s) to $OUT_BASE/{univ1,univ2}/cache_sim/source_seen/plots"
