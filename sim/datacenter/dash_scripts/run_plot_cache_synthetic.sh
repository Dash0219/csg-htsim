#!/usr/bin/env bash
set -euo pipefail

print_usage() {
  cat <<'EOF'
Usage:
  bash dash_scripts/run_plot_cache_synthetic.sh [OUT_DIR] [options]

Options:
  -d, --dataset NAME        Only plot one synthetic dataset (e.g., a2a_pareto)
  -p, --protocol NAME       Transport protocol: ndp or hpcc (default: ndp)
  -m, --mode MODE           route_changes | source_seen | congestion | all (default: all)
  -n, --scale-to-infinite   Scale y-axis using observed infinite/data range
      --scale-factor X      Headroom multiplier with --scale-to-infinite (default: 1.25)
      --max-concurrency N   Override concurrency marker capacity (default: inferred per dataset)
      --no-max-concurrency  Disable concurrency marker
      --unique-flows N      Override unique-flow marker capacity (default: inferred per dataset)
      --no-unique-flows     Disable unique-flow marker
      --qs-threshold N      Congestion threshold in bytes for congestion markers (default: 50000)
      --key-level MODE      Congestion key mode: switch | flow (default: switch)
      --no-congestion-markers Disable inferred congestion markers
      --switch-budget N     Optional practical switch cache-size marker
      --hide-limit-labels   Draw limit lines without text labels
      --disable-policy NAME Hide one policy in plots (repeatable)
      --include-policy NAME Keep only selected policies (repeatable)
      --hide-redundant-pairs Hide near-duplicate policies in final figures
  -h, --help                Show this help
EOF
}

DATASET="${DATASET:-}"
LOW_TEMP_LOCALITY="${LOW_TEMP_LOCALITY:-0}"
LOW_TEMP_SUFFIX="${LOW_TEMP_SUFFIX:-low_temp_locality}"
MODE="${MODE:-all}"
PROTOCOL="${PROTOCOL:-ndp}"
SCALE_TO_INFINITE="${SCALE_TO_INFINITE:-0}"
SCALE_FACTOR="${SCALE_FACTOR:-1.25}"
MAX_CONCURRENCY="${MAX_CONCURRENCY:-0}"
UNIQUE_FLOWS="${UNIQUE_FLOWS:-0}"
USE_MAX_CONCURRENCY=1
USE_UNIQUE_FLOWS=1
SWITCH_BUDGET="${SWITCH_BUDGET:-0}"
QS_THRESHOLD="${QS_THRESHOLD:-50000}"
KEY_LEVEL="${KEY_LEVEL:-switch}"
USE_CONGESTION_MARKERS=1
HIDE_LIMIT_LABELS=0
HIDE_REDUNDANT_PAIRS=0
declare -a DISABLE_POLICIES=()
declare -a INCLUDE_POLICIES=()

OUT_DIR=""
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
    -p|--protocol)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --protocol requires a value" >&2
        exit 1
      fi
      PROTOCOL="$2"
      shift 2
      ;;
    -m|--mode)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --mode requires a value" >&2
        exit 1
      fi
      MODE="$2"
      shift 2
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
    --qs-threshold)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --qs-threshold requires a value" >&2
        exit 1
      fi
      QS_THRESHOLD="$2"
      shift 2
      ;;
    --key-level)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --key-level requires a value" >&2
        exit 1
      fi
      KEY_LEVEL="$2"
      shift 2
      ;;
    --no-congestion-markers)
      USE_CONGESTION_MARKERS=0
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
    -h|--help)
      print_usage
      exit 0
      ;;
    *)
      if [[ -z "$OUT_DIR" ]]; then
        OUT_DIR="$1"
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

if [[ "$MODE" != "route_changes" && "$MODE" != "source_seen" && "$MODE" != "congestion" && "$MODE" != "all" ]]; then
  echo "ERROR: --mode must be route_changes, source_seen, congestion, or all" >&2
  exit 1
fi

if [[ "$KEY_LEVEL" != "switch" && "$KEY_LEVEL" != "flow" ]]; then
  echo "ERROR: --key-level must be switch or flow" >&2
  exit 1
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

if [[ "$PROTOCOL" != "ndp" && "$PROTOCOL" != "hpcc" ]]; then
  echo "ERROR: --protocol must be ndp or hpcc" >&2
  exit 1
fi

OUT_DIR="${OUT_DIR:-dash_results/synthetic/${PROTOCOL}/cache_sim}"
FLOW_STATS_DIR="dash_results/synthetic/${PROTOCOL}/flow_stats"
mkdir -p "$OUT_DIR"

count=0

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

infer_dataset_max_concurrency() {
  local dataset_name="$1"
  local stats_file="$FLOW_STATS_DIR/${dataset_name}_flow_stats.txt"
  if [[ ! -f "$stats_file" ]]; then
    return
  fi
  local maxc=""
  maxc=$(grep -E 'Peak concurrency:|Max peak concurrency' "$stats_file" 2>/dev/null \
    | sed -E 's/.*: *([0-9][0-9,]*).*/\1/' \
    | tr -d ',' \
    | awk 'max<$1{max=$1} END{if(max>0) print max}')
  if [[ -n "$maxc" ]]; then
    echo "$maxc"
  fi
}

infer_dataset_unique_flows() {
  local dataset_name="$1"
  local stats_file="$FLOW_STATS_DIR/${dataset_name}_flow_stats.txt"
  if [[ ! -f "$stats_file" ]]; then
    return
  fi
  local uniq=""
  uniq=$(grep -E 'Unique flows:' "$stats_file" 2>/dev/null \
    | sed -E 's/.*: *([0-9][0-9,]*).*/\1/' \
    | tr -d ',' \
    | awk 'max<$1{max=$1} END{if(max>0) print max}')
  if [[ -n "$uniq" ]]; then
    echo "$uniq"
  fi
}

run_plot() {
  local csv="$1"
  local out_sub="$2"
  local stem="$3"
  local concurrency="$4"
  local unique_flows="$5"
  shift 5
  local args=(--out "$out_sub" --prefix "$stem")
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
  for marker in "$@"; do
    args+=(--marker "$marker")
  done
  python3 dash_scripts/plot_cache.py "$csv" "${args[@]}"
}

infer_congestion_limits() {
  local dataset_name="$1"
  local log_file="dash_dataset/synthetic/${PROTOCOL}/log_${dataset_name}.txt"
  if [[ ! -f "$log_file" ]]; then
    return
  fi
  python3 - "$log_file" "$QS_THRESHOLD" "$KEY_LEVEL" <<'PY'
import re
import sys
from collections import defaultdict

log_file = sys.argv[1]
qs_threshold = int(sys.argv[2])
key_level = sys.argv[3]

header_re = re.compile(r"INT flow=(\d+) seq=(\d+) hops=(\d+)")
hop_re = re.compile(r"\[(\d+)\] sw=(\d+) type=(\d+) qs=(\d+) ts=(\d+)")

event_keys_by_ts = defaultdict(set)
unique_keys = set()

current = None

def process(rec):
    if not rec:
        return
    flow = rec["flow"]
    hops = rec["hops"]
    if key_level == "flow":
        congested_ts = [ts for _, _, qs, ts in hops if qs >= qs_threshold]
        if not congested_ts:
            return
        ts = max(congested_ts)
        key = str(flow)
        event_keys_by_ts[ts].add(key)
        unique_keys.add(key)
        return

    seen_this_packet = {}
    for sw, stype, qs, ts in hops:
        if qs < qs_threshold:
            continue
        key = f"{sw}:{stype}"
        prev_ts = seen_this_packet.get(key)
        if prev_ts is None or ts > prev_ts:
            seen_this_packet[key] = ts
    for key, ts in seen_this_packet.items():
        event_keys_by_ts[ts].add(key)
        unique_keys.add(key)

with open(log_file) as f:
    for line in f:
        hm = header_re.search(line)
        if hm:
            process(current)
            current = {"flow": int(hm.group(1)), "hops": []}
            continue
        if current is None:
            continue
        hm = hop_re.search(line)
        if hm:
            current["hops"].append((
                int(hm.group(2)),
                int(hm.group(3)),
                int(hm.group(4)),
                int(hm.group(5)),
            ))
process(current)

peak = 0
for keys in event_keys_by_ts.values():
    if len(keys) > peak:
        peak = len(keys)
print(f"{peak} {len(unique_keys)}")
PY
}

plot_mode() {
  local mode="$1"
  local in_dir="$2"
  local legacy_glob="$3"
  local out_sub="$OUT_DIR/$mode/plots"
  local prefix_base="$4"
  mkdir -p "$out_sub"

  local any=0
  if [[ -d "$in_dir" ]]; then
    for csv in "$in_dir"/*.csv; do
      [[ -f "$csv" ]] || continue
      any=1
      stem="$(basename "$csv" .csv)"
      dataset_name="${stem#${prefix_base}}"
      if [[ "$LOW_TEMP_LOCALITY" == "1" && "$dataset_name" != *"_${LOW_TEMP_SUFFIX}" ]]; then
        continue
      fi
      if [[ "$LOW_TEMP_LOCALITY" == "0" && "$dataset_name" == *"_${LOW_TEMP_SUFFIX}" ]]; then
        continue
      fi
      if [[ -n "$DATASET" && "$dataset_name" != "$DATASET" ]]; then
        continue
      fi
      use_concurrency="0"
      use_unique_flows="0"
      declare -a markers=()
      if [[ "$mode" == "congestion" ]]; then
        if [[ "$USE_CONGESTION_MARKERS" == "1" ]]; then
          inferred_congestion="$(infer_congestion_limits "$dataset_name" || true)"
          if [[ -n "$inferred_congestion" ]]; then
            peak_keys="$(echo "$inferred_congestion" | awk '{print $1}')"
            unique_keys="$(echo "$inferred_congestion" | awk '{print $2}')"
            if [[ -n "$peak_keys" && "$peak_keys" != "0" ]]; then
              markers+=("peak congested keys=$peak_keys")
            fi
            if [[ -n "$unique_keys" && "$unique_keys" != "0" ]]; then
              markers+=("unique congested keys=$unique_keys")
            fi
          fi
        fi
      else
        use_concurrency="$MAX_CONCURRENCY"
        if [[ "$USE_MAX_CONCURRENCY" == "0" ]]; then
          use_concurrency="0"
        elif [[ -z "$use_concurrency" || "$use_concurrency" == "0" ]]; then
          inferred=$(infer_dataset_max_concurrency "$dataset_name")
          if [[ -n "$inferred" ]]; then
            use_concurrency="$inferred"
          fi
        fi
        use_unique_flows="$UNIQUE_FLOWS"
        if [[ "$USE_UNIQUE_FLOWS" == "0" ]]; then
          use_unique_flows="0"
        elif [[ -z "$use_unique_flows" || "$use_unique_flows" == "0" ]]; then
          inferred_unique=$(infer_dataset_unique_flows "$dataset_name")
          if [[ -n "$inferred_unique" ]]; then
            use_unique_flows="$inferred_unique"
          fi
        fi
      fi
      echo "== plotting $mode/$stem =="
      if [[ ${#markers[@]} -gt 0 ]]; then
        run_plot "$csv" "$out_sub" "$stem" "$use_concurrency" "$use_unique_flows" "${markers[@]}"
      else
        run_plot "$csv" "$out_sub" "$stem" "$use_concurrency" "$use_unique_flows"
      fi
      count=$((count + 1))
    done
  fi

  # Legacy fallback to ease migration for already-generated CSVs.
  if [[ "$any" == "0" ]]; then
    for csv in $legacy_glob; do
      [[ -f "$csv" ]] || continue
      stem="$(basename "$csv" .csv)"
      dataset_name="${stem#${prefix_base}}"
      if [[ "$LOW_TEMP_LOCALITY" == "1" && "$dataset_name" != *"_${LOW_TEMP_SUFFIX}" ]]; then
        continue
      fi
      if [[ "$LOW_TEMP_LOCALITY" == "0" && "$dataset_name" == *"_${LOW_TEMP_SUFFIX}" ]]; then
        continue
      fi
      if [[ -n "$DATASET" && "$dataset_name" != "$DATASET" ]]; then
        continue
      fi
      use_concurrency="0"
      use_unique_flows="0"
      declare -a markers=()
      if [[ "$mode" == "congestion" ]]; then
        if [[ "$USE_CONGESTION_MARKERS" == "1" ]]; then
          inferred_congestion="$(infer_congestion_limits "$dataset_name" || true)"
          if [[ -n "$inferred_congestion" ]]; then
            peak_keys="$(echo "$inferred_congestion" | awk '{print $1}')"
            unique_keys="$(echo "$inferred_congestion" | awk '{print $2}')"
            if [[ -n "$peak_keys" && "$peak_keys" != "0" ]]; then
              markers+=("peak congested keys=$peak_keys")
            fi
            if [[ -n "$unique_keys" && "$unique_keys" != "0" ]]; then
              markers+=("unique congested keys=$unique_keys")
            fi
          fi
        fi
      else
        use_concurrency="$MAX_CONCURRENCY"
        if [[ "$USE_MAX_CONCURRENCY" == "0" ]]; then
          use_concurrency="0"
        elif [[ -z "$use_concurrency" || "$use_concurrency" == "0" ]]; then
          inferred=$(infer_dataset_max_concurrency "$dataset_name")
          if [[ -n "$inferred" ]]; then
            use_concurrency="$inferred"
          fi
        fi
        use_unique_flows="$UNIQUE_FLOWS"
        if [[ "$USE_UNIQUE_FLOWS" == "0" ]]; then
          use_unique_flows="0"
        elif [[ -z "$use_unique_flows" || "$use_unique_flows" == "0" ]]; then
          inferred_unique=$(infer_dataset_unique_flows "$dataset_name")
          if [[ -n "$inferred_unique" ]]; then
            use_unique_flows="$inferred_unique"
          fi
        fi
      fi
      echo "== plotting legacy $mode/$stem =="
      if [[ ${#markers[@]} -gt 0 ]]; then
        run_plot "$csv" "$out_sub" "$stem" "$use_concurrency" "$use_unique_flows" "${markers[@]}"
      else
        run_plot "$csv" "$out_sub" "$stem" "$use_concurrency" "$use_unique_flows"
      fi
      count=$((count + 1))
    done
  fi
}

if [[ "$MODE" == "route_changes" || "$MODE" == "all" ]]; then
  plot_mode "route_changes" \
    "dash_results/synthetic/${PROTOCOL}/cache_sim/route_changes" \
    "dash_results/synthetic/cache_sim/route_change/results_synthetic_*.csv" \
    "results_synthetic_"
fi

if [[ "$MODE" == "source_seen" || "$MODE" == "all" ]]; then
  plot_mode "source_seen" \
    "dash_results/synthetic/${PROTOCOL}/cache_sim/source_seen" \
    "" \
    "results_synthetic_source_seen_"
fi

if [[ "$MODE" == "congestion" || "$MODE" == "all" ]]; then
  plot_mode "congestion" \
    "dash_results/synthetic/${PROTOCOL}/cache_sim/congestion" \
    "" \
    "results_synthetic_congestion_"
fi

echo "Done. Plotted $count synthetic CSV file(s) to $OUT_DIR"
