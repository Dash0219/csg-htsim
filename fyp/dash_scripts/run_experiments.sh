#!/usr/bin/env bash
set -euo pipefail

print_usage() {
  cat <<'EOF'
Usage:
  bash fyp/dash_scripts/run_experiments.sh [options]

Options:
  -e, --experiments LIST     Comma-separated experiment IDs to run (default: 1,2,3,4)
  -p, --protocol NAME        Synthetic transport protocol for thesis experiments (default: ndp)
  -t, --topology NAME        Synthetic topology family: a2a or incast (default: a2a)
  -a, --anchor NAME          Anchor dataset (default: <topology>_pareto_alpha_1p0)
      --flow-size-values L   Comma-separated mono packet-count values for flow-size axis
      --burst-values L       Comma-separated ROUTE_PATH_BURST values for mono-burst axis
      --temporal-values L    Comma-separated temporal spread multipliers for *_temp_<N> datasets
      --pareto-alpha-values L Comma-separated Pareto alpha values for skew sweep datasets
      --exp34-temporal-all   Use all temporal values in experiments 3 and 4 (default)
      --exp34-temporal-tail  Use only the highest temporal value in experiments 3 and 4
  -f, --fast                 Force fast cache simulator path (default)
      --no-fast              Disable fast cache simulator path
      --no-generate          Reuse-only mode: fail if required log/CSV is missing
      --results-root DIR     Override experiment output root (default: fyp/dash_results/experiments)
  -h, --help                 Show this help

Experiment mapping:
  1: Workload matrix (4 axes)
  2: Pressure sweep (capacity-pressure breakdown)
  3: Admission study (admission-family deltas vs LRU)
  4: TTL/freshness study (TTL/freshness failure analysis)
EOF
}

EXPERIMENTS_RAW="${EXPERIMENTS:-1,2,3,4}"
PROTOCOL="${PROTOCOL:-ndp}"
TOPOLOGY="${TOPOLOGY:-a2a}"
ANCHOR_DATASET="${ANCHOR_DATASET:-}"
FLOW_SIZE_VALUES="${FLOW_SIZE_SWEEP_VALUES:-1,2,4,8,16,32,64,128,256,512,1024,2048,4096}"
BURST_VALUES="${BURST_SWEEP_VALUES:-8,16,32,64,128,256}"
TEMPORAL_VALUES="${TEMPORAL_SWEEP_VALUES:-1,2,4,8}"
PARETO_ALPHA_VALUES="${PARETO_ALPHA_SWEEP_VALUES:-1.0,1.5,2.0,2.5,3.0,3.5}"
EXP34_TEMPORAL_ALL="${EXP34_TEMPORAL_ALL:-1}"
FAST="${FAST:-1}"
NO_GENERATE="${NO_GENERATE:-0}"
RESULTS_ROOT="${RESULTS_ROOT:-fyp/dash_results/experiments}"
FLOW_STATS_DIR="fyp/dash_results/synthetic/${PROTOCOL}/flow_stats"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -e|--experiments)
      [[ $# -ge 2 ]] || { echo "ERROR: --experiments requires a value" >&2; exit 1; }
      EXPERIMENTS_RAW="$2"
      shift 2
      ;;
    -p|--protocol)
      [[ $# -ge 2 ]] || { echo "ERROR: --protocol requires a value" >&2; exit 1; }
      PROTOCOL="$2"
      shift 2
      ;;
    -t|--topology)
      [[ $# -ge 2 ]] || { echo "ERROR: --topology requires a value" >&2; exit 1; }
      TOPOLOGY="$2"
      shift 2
      ;;
    -a|--anchor)
      [[ $# -ge 2 ]] || { echo "ERROR: --anchor requires a value" >&2; exit 1; }
      ANCHOR_DATASET="$2"
      shift 2
      ;;
    --flow-size-values)
      [[ $# -ge 2 ]] || { echo "ERROR: --flow-size-values requires a value" >&2; exit 1; }
      FLOW_SIZE_VALUES="$2"
      shift 2
      ;;
    --burst-values)
      [[ $# -ge 2 ]] || { echo "ERROR: --burst-values requires a value" >&2; exit 1; }
      BURST_VALUES="$2"
      shift 2
      ;;
    --temporal-values)
      [[ $# -ge 2 ]] || { echo "ERROR: --temporal-values requires a value" >&2; exit 1; }
      TEMPORAL_VALUES="$2"
      shift 2
      ;;
    --pareto-alpha-values)
      [[ $# -ge 2 ]] || { echo "ERROR: --pareto-alpha-values requires a value" >&2; exit 1; }
      PARETO_ALPHA_VALUES="$2"
      shift 2
      ;;
    --exp34-temporal-all)
      EXP34_TEMPORAL_ALL=1
      shift
      ;;
    --exp34-temporal-tail)
      EXP34_TEMPORAL_ALL=0
      shift
      ;;
    -f|--fast)
      FAST=1
      shift
      ;;
    --no-fast)
      FAST=0
      shift
      ;;
    --no-generate)
      NO_GENERATE=1
      shift
      ;;
    --results-root)
      [[ $# -ge 2 ]] || { echo "ERROR: --results-root requires a value" >&2; exit 1; }
      RESULTS_ROOT="$2"
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
if [[ "$TOPOLOGY" != "a2a" && "$TOPOLOGY" != "incast" ]]; then
  echo "ERROR: --topology must be a2a or incast" >&2
  exit 1
fi
if [[ "$FAST" != "0" && "$FAST" != "1" ]]; then
  echo "ERROR: FAST must be 0 or 1" >&2
  exit 1
fi

if [[ -z "$ANCHOR_DATASET" ]]; then
  ANCHOR_DATASET="${TOPOLOGY}_pareto_alpha_1p0"
fi

SELECTED_EXPS=()
IFS=',' read -r -a _exp_parts <<< "$EXPERIMENTS_RAW"
for raw in "${_exp_parts[@]}"; do
  exp="${raw//[[:space:]]/}"
  [[ -n "$exp" ]] || continue
  if ! [[ "$exp" =~ ^[1-4]$ ]]; then
    echo "ERROR: invalid experiment id '$exp' (expected 1..4)" >&2
    exit 1
  fi
  SELECTED_EXPS+=("$exp")
done
if [[ ${#SELECTED_EXPS[@]} -eq 0 ]]; then
  echo "ERROR: no experiments selected" >&2
  exit 1
fi

TEMPORAL_TAIL=1
IFS=',' read -r -a _temp_tail_parts <<< "$TEMPORAL_VALUES"
for _t in "${_temp_tail_parts[@]}"; do
  _t="${_t//[[:space:]]/}"
  [[ -n "$_t" ]] || continue
  TEMPORAL_TAIL="$_t"
done

mkdir -p "$RESULTS_ROOT"
mkdir -p "$FLOW_STATS_DIR"

run_exp() {
  local target="$1"
  local x
  for x in "${SELECTED_EXPS[@]}"; do
    if [[ "$x" == "$target" ]]; then
      return 0
    fi
  done
  return 1
}

fail_no_generate() {
  local missing_desc="$1"
  local hint="$2"
  echo "ERROR: missing ${missing_desc} and --no-generate is set" >&2
  if [[ -n "$hint" ]]; then
    echo "Hint: $hint" >&2
  fi
  exit 1
}

is_flow_size_dataset() {
  local name="$1"
  [[ "$name" =~ ^(incast|a2a)_mono_[0-9]+$ ]]
}

is_burst_dataset() {
  local name="$1"
  [[ "$name" =~ ^(incast|a2a)_mono_burst_([0-9]+)$ ]]
}

is_temporal_dataset() {
  local name="$1"
  [[ "$name" =~ ^(incast|a2a)_pareto_temp_([0-9]+)$ ]]
}

is_pareto_alpha_dataset() {
  local name="$1"
  [[ "$name" =~ ^(incast|a2a)_pareto_alpha_[0-9]+(p[0-9]+)?$ ]]
}

dataset_log_path() {
  local dataset="$1"
  echo "fyp/dash_dataset/synthetic/${PROTOCOL}/log_${dataset}.txt"
}

dataset_csv_path() {
  local dataset="$1"
  echo "fyp/dash_results/synthetic/${PROTOCOL}/cache_sim/route_changes/results_synthetic_${dataset}.csv"
}

ensure_dataset_log() {
  local dataset="$1"
  local log_path
  log_path="$(dataset_log_path "$dataset")"
  if [[ -f "$log_path" ]]; then
    return
  fi

  if [[ "$NO_GENERATE" == "1" ]]; then
    fail_no_generate "dataset log ${log_path}" "bash fyp/dash_scripts/run_htsim_synthetic.sh --protocol ${PROTOCOL} --dataset ${dataset}"
  fi

  echo "  generating missing dataset log: ${dataset}"
  if is_flow_size_dataset "$dataset"; then
    local fs
    fs="${dataset##*_}"
    GENERATE_FLOW_SIZE_SWEEP=1 FLOW_SIZE_SWEEP_VALUES="$fs" \
      bash fyp/dash_scripts/run_htsim_synthetic.sh --protocol "$PROTOCOL" --dataset "$dataset"
    return
  fi

  if is_burst_dataset "$dataset"; then
    local bs
    bs="${dataset##*_}"
    GENERATE_BURST_SWEEP=1 BURST_SWEEP_VALUES="$bs" \
      bash fyp/dash_scripts/run_htsim_synthetic.sh --protocol "$PROTOCOL" --dataset "$dataset"
    return
  fi

  if is_temporal_dataset "$dataset"; then
    local tv
    tv="${dataset##*_}"
    GENERATE_TEMPORAL_SWEEP=1 TEMPORAL_SWEEP_VALUES="$tv" \
      bash fyp/dash_scripts/run_htsim_synthetic.sh --protocol "$PROTOCOL" --dataset "$dataset"
    return
  fi

  if is_pareto_alpha_dataset "$dataset"; then
    local alpha_tok
    local alpha
    alpha_tok="${dataset##*_}"
    alpha="${alpha_tok/p/.}"
    GENERATE_PARETO_SKEW_SWEEP=1 PARETO_ALPHA_SWEEP_VALUES="$alpha" \
      bash fyp/dash_scripts/run_htsim_synthetic.sh --protocol "$PROTOCOL" --dataset "$dataset"
    return
  fi

  bash fyp/dash_scripts/run_htsim_synthetic.sh --protocol "$PROTOCOL" --dataset "$dataset"
}

ensure_route_csv() {
  local dataset="$1"
  local csv_path
  csv_path="$(dataset_csv_path "$dataset")"
  if [[ -f "$csv_path" ]]; then
    return
  fi

  if [[ "$NO_GENERATE" == "1" ]]; then
    fail_no_generate "route-change CSV ${csv_path}" "bash fyp/dash_scripts/run_cache_sim_synthetic.sh --protocol ${PROTOCOL} --dataset ${dataset}"
  fi

  echo "  generating missing cache CSV: ${dataset}"
  if [[ "$FAST" == "1" ]]; then
    bash fyp/dash_scripts/run_cache_sim_synthetic.sh --protocol "$PROTOCOL" --dataset "$dataset" --fast
  else
    bash fyp/dash_scripts/run_cache_sim_synthetic.sh --protocol "$PROTOCOL" --dataset "$dataset" --no-fast
  fi
}

copy_csv_for_exp() {
  local dataset="$1"
  local out_dir="$2"
  mkdir -p "$out_dir"
  cp "$(dataset_csv_path "$dataset")" "$out_dir/"
}

flow_stats_txt_path() {
  local dataset="$1"
  echo "$FLOW_STATS_DIR/${dataset}_flow_stats.txt"
}

flow_stats_csv_path() {
  local dataset="$1"
  echo "$FLOW_STATS_DIR/${dataset}_flow_stats.csv"
}

ensure_flow_stats() {
  local dataset="$1"
  local logfile
  local out_txt
  local out_csv
  logfile="$(dataset_log_path "$dataset")"
  out_txt="$(flow_stats_txt_path "$dataset")"
  out_csv="$(flow_stats_csv_path "$dataset")"

  if [[ ! -f "$logfile" ]]; then
    return
  fi

  if [[ -f "$out_txt" && -f "$out_csv" ]]; then
    if [[ "$out_txt" -nt "$logfile" && "$out_csv" -nt "$logfile" ]]; then
      return
    fi
  fi

  echo "  generating flow stats: ${dataset}"
  python3 fyp/dash_scripts/flow_stats.py "$logfile" --top 20 --concurrency --csv "$out_csv" > "$out_txt"
}

infer_dataset_max_concurrency() {
  local dataset="$1"
  local stats_file
  stats_file="$(flow_stats_txt_path "$dataset")"
  [[ -f "$stats_file" ]] || return

  grep -E 'Peak concurrency:|Max peak concurrency' "$stats_file" 2>/dev/null \
    | sed -E 's/.*: *([0-9][0-9,]*).*/\1/' \
    | tr -d ',' \
    | awk 'max<$1{max=$1} END{if(max>0) print max}'
}

infer_dataset_unique_flows() {
  local dataset="$1"
  local stats_file
  stats_file="$(flow_stats_txt_path "$dataset")"
  [[ -f "$stats_file" ]] || return

  grep -E 'Unique flows:' "$stats_file" 2>/dev/null \
    | sed -E 's/.*: *([0-9][0-9,]*).*/\1/' \
    | tr -d ',' \
    | awk 'max<$1{max=$1} END{if(max>0) print max}'
}

plot_csv_if_missing() {
  local csv_path="$1"
  local out_dir="$2"
  local prefix="$3"
  local include_policies="${4:-}"
  local dataset_name="${5:-}"

  if [[ -n "$dataset_name" ]]; then
    ensure_flow_stats "$dataset_name"
  fi

  mkdir -p "$out_dir"
  local p1="$out_dir/${prefix}_suppression_vs_capacity.png"
  local p2="$out_dir/${prefix}_redundancy_vs_capacity.png"
  if [[ -f "$p1" && -f "$p2" ]]; then
    return
  fi

  local args=("$csv_path" --out "$out_dir" --prefix "$prefix" --scale-to-infinite)

  if [[ -n "$dataset_name" ]]; then
    local max_concurrency=""
    local unique_flows=""
    max_concurrency="$(infer_dataset_max_concurrency "$dataset_name" || true)"
    unique_flows="$(infer_dataset_unique_flows "$dataset_name" || true)"
    if [[ -n "$max_concurrency" && "$max_concurrency" != "0" ]]; then
      args+=(--max-concurrency "$max_concurrency")
    fi
    if [[ -n "$unique_flows" && "$unique_flows" != "0" ]]; then
      args+=(--unique-flows "$unique_flows")
    fi
  fi

  if [[ -n "$include_policies" ]]; then
    args+=(--include-policies "$include_policies")
  fi
  python3 fyp/dash_scripts/plot_cache.py "${args[@]}"
}

write_flow_stats_summary() {
  local out_csv="$1"
  local protocol="$2"
  shift 2
  python3 - "$out_csv" "$protocol" "$@" <<'PY'
import csv
import os
import re
import sys

out_csv = sys.argv[1]
protocol = sys.argv[2]
datasets = []
seen = set()
for ds in sys.argv[3:]:
  if ds in seen:
    continue
  seen.add(ds)
  datasets.append(ds)
rows = []

for ds in datasets:
    txt = f"fyp/dash_results/synthetic/{protocol}/flow_stats/{ds}_flow_stats.txt"
    if not os.path.exists(txt):
        continue
    unique = None
    peak = None
    avg = None
    with open(txt, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = re.search(r"Unique flows:\s*([0-9][0-9,]*)", line)
            if m:
                unique = int(m.group(1).replace(",", ""))
            m = re.search(r"Peak concurrency:\s*([0-9][0-9,]*)", line)
            if m:
                peak = int(m.group(1).replace(",", ""))
            m = re.search(r"Avg concurrency:\s*([0-9]+(?:\.[0-9]+)?)", line)
            if m:
                avg = float(m.group(1))
    rows.append({
        "dataset": ds,
        "unique_flows": unique if unique is not None else 0,
        "max_concurrent_flows": peak if peak is not None else 0,
        "avg_concurrent_flows": avg if avg is not None else 0.0,
    })

with open(out_csv, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["dataset", "unique_flows", "max_concurrent_flows", "avg_concurrent_flows"])
    w.writeheader()
    w.writerows(rows)
PY
}

generate_comparison_plots() {
  local exp_root="$1"
  local exp_name="$2"
  local flow_csv="${3:-}"
  local out_dir="$exp_root/comparison_plots"
  mkdir -p "$out_dir"

  local args=(--experiment "$exp_name" --exp-root "$exp_root" --out "$out_dir")
  if [[ -n "$flow_csv" && -f "$flow_csv" ]]; then
    args+=(--flow-stats-csv "$flow_csv")
  fi
  python3 fyp/dash_scripts/plot_experiment_comparisons.py "${args[@]}"
}

write_axis_summary() {
  local axis_name="$1"
  local axis_dir="$2"
  local out_csv="$3"
  python3 - "$axis_name" "$axis_dir" "$out_csv" <<'PY'
import csv
import glob
import os
import sys

axis_name, axis_dir, out_csv = sys.argv[1:4]
paths = sorted(glob.glob(os.path.join(axis_dir, "results_synthetic_*.csv")))
rows = []
for path in paths:
    dataset = os.path.basename(path).replace("results_synthetic_", "").replace(".csv", "")
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({
                "axis": axis_name,
                "dataset": dataset,
                "cache": r["cache"],
                "capacity": int(float(r["capacity"])),
                "suppression_rate": float(r["suppression_rate"]),
                "redundancy_rate": float(r["redundancy_rate"]),
                "evictions": int(float(r["evictions"])),
            })

with open(out_csv, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["axis", "dataset", "cache", "capacity", "suppression_rate", "redundancy_rate", "evictions"])
    w.writeheader()
    w.writerows(rows)
PY
}

exp1_workload_matrix() {
  echo "[exp1] Workload matrix (4 axes)"

  local exp_root="$RESULTS_ROOT/exp1_workload_matrix"
  local skew_dir="$exp_root/skew"
  local burst_dir="$exp_root/burstiness"
  local flow_dir="$exp_root/flow_size"
  local temp_dir="$exp_root/temporal_locality"
  mkdir -p "$skew_dir" "$burst_dir" "$flow_dir" "$temp_dir"

  local skew_sets=()
  local a
  IFS=',' read -r -a _alpha_parts <<< "$PARETO_ALPHA_VALUES"
  for a in "${_alpha_parts[@]}"; do
    a="${a//[[:space:]]/}"
    [[ -n "$a" ]] || continue
    skew_sets+=("${TOPOLOGY}_pareto_alpha_${a//./p}")
  done
  if [[ ${#skew_sets[@]} -eq 0 ]]; then
    skew_sets=("${TOPOLOGY}_pareto_alpha_1p0")
  fi

  local flow_sets=()
  local fs
  IFS=',' read -r -a _flow_parts <<< "$FLOW_SIZE_VALUES"
  for fs in "${_flow_parts[@]}"; do
    fs="${fs//[[:space:]]/}"
    [[ -n "$fs" ]] || continue
    flow_sets+=("${TOPOLOGY}_mono_${fs}")
  done

  local burst_sets=()
  local bs
  IFS=',' read -r -a _burst_parts <<< "$BURST_VALUES"
  for bs in "${_burst_parts[@]}"; do
    bs="${bs//[[:space:]]/}"
    [[ -n "$bs" ]] || continue
    burst_sets+=("${TOPOLOGY}_mono_burst_${bs}")
  done

  local temp_sets=()
  local tv
  IFS=',' read -r -a _temp_parts <<< "$TEMPORAL_VALUES"
  for tv in "${_temp_parts[@]}"; do
    tv="${tv//[[:space:]]/}"
    [[ -n "$tv" ]] || continue
    temp_sets+=("${TOPOLOGY}_pareto_temp_${tv}")
  done
  if [[ ${#temp_sets[@]} -eq 0 ]]; then
    temp_sets=("${TOPOLOGY}_pareto_temp_1")
  fi

  local ds
  for ds in "${skew_sets[@]}"; do
    ensure_dataset_log "$ds"
    ensure_route_csv "$ds"
    copy_csv_for_exp "$ds" "$skew_dir"
    plot_csv_if_missing "$(dataset_csv_path "$ds")" "$skew_dir/plots" "results_synthetic_${ds}" "" "$ds"
  done

  for ds in "${burst_sets[@]}"; do
    ensure_dataset_log "$ds"
    ensure_route_csv "$ds"
    copy_csv_for_exp "$ds" "$burst_dir"
    plot_csv_if_missing "$(dataset_csv_path "$ds")" "$burst_dir/plots" "results_synthetic_${ds}" "" "$ds"
  done

  for ds in "${flow_sets[@]}"; do
    ensure_dataset_log "$ds"
    ensure_route_csv "$ds"
    copy_csv_for_exp "$ds" "$flow_dir"
    plot_csv_if_missing "$(dataset_csv_path "$ds")" "$flow_dir/plots" "results_synthetic_${ds}" "" "$ds"
  done

  for ds in "${temp_sets[@]}"; do
    ensure_dataset_log "$ds"
    ensure_route_csv "$ds"
    copy_csv_for_exp "$ds" "$temp_dir"
    plot_csv_if_missing "$(dataset_csv_path "$ds")" "$temp_dir/plots" "results_synthetic_${ds}" "" "$ds"
  done

  write_axis_summary "skew" "$skew_dir" "$exp_root/skew_axis_summary.csv"
  write_axis_summary "burstiness" "$burst_dir" "$exp_root/burstiness_axis_summary.csv"
  write_axis_summary "flow_size" "$flow_dir" "$exp_root/flow_size_axis_summary.csv"
  write_axis_summary "temporal_locality" "$temp_dir" "$exp_root/temporal_locality_axis_summary.csv"

  write_flow_stats_summary "$exp_root/flow_stats_summary.csv" "$PROTOCOL" \
    "${skew_sets[@]}" "${burst_sets[@]}" "${flow_sets[@]}" "${temp_sets[@]}"
  generate_comparison_plots "$exp_root" "exp1" "$exp_root/flow_stats_summary.csv"
}

collect_exp34_temporal_sets() {
  local out=()
  if [[ "$EXP34_TEMPORAL_ALL" == "1" ]]; then
    local tv
    IFS=',' read -r -a _temp_parts <<< "$TEMPORAL_VALUES"
    for tv in "${_temp_parts[@]}"; do
      tv="${tv//[[:space:]]/}"
      [[ -n "$tv" ]] || continue
      out+=("${TOPOLOGY}_pareto_temp_${tv}")
    done
  else
    out+=("${TOPOLOGY}_pareto_temp_${TEMPORAL_TAIL}")
  fi
  if [[ ${#out[@]} -eq 0 ]]; then
    out+=("${TOPOLOGY}_pareto_temp_1")
  fi
  printf '%s\n' "${out[@]}"
}

exp2_pressure_sweep() {
  echo "[exp2] Pressure sweep"

  local exp_root="$RESULTS_ROOT/exp2_pressure"
  mkdir -p "$exp_root/csv" "$exp_root/plots"

  local pressure_sets=(
    "$ANCHOR_DATASET"
    "${TOPOLOGY}_mono_burst_64"
    "${TOPOLOGY}_mono_256"
    "${TOPOLOGY}_pareto_temp_${TEMPORAL_TAIL}"
  )

  local ds
  for ds in "${pressure_sets[@]}"; do
    ensure_dataset_log "$ds"
    ensure_route_csv "$ds"
    copy_csv_for_exp "$ds" "$exp_root/csv"
    plot_csv_if_missing "$(dataset_csv_path "$ds")" "$exp_root/plots" "results_synthetic_${ds}" "" "$ds"
  done

  write_flow_stats_summary "$exp_root/flow_stats_summary.csv" "$PROTOCOL" "${pressure_sets[@]}"

  python3 - "$exp_root" <<'PY'
import csv
import glob
import os
import sys

exp_root = sys.argv[1]
out_csv = os.path.join(exp_root, "pressure_summary.csv")

rows = []
for path in sorted(glob.glob(os.path.join(exp_root, "csv", "results_synthetic_*.csv"))):
    dataset = os.path.basename(path).replace("results_synthetic_", "").replace(".csv", "")
    oracle_suppression = None
    with open(path, newline="") as f:
        reader = list(csv.DictReader(f))
    for r in reader:
        if r["cache"] == "Infinite":
            oracle_suppression = float(r["suppression_rate"])
            break

    for r in reader:
        cap = int(float(r["capacity"]))
        total = max(1.0, float(r["total"]))
        suppression = float(r["suppression_rate"])
        oracle = oracle_suppression if oracle_suppression is not None else suppression
        rows.append({
            "dataset": dataset,
            "cache": r["cache"],
            "capacity": cap,
            "suppression_rate": suppression,
            "redundancy_rate": float(r["redundancy_rate"]),
            "eviction_pressure": float(r["evictions"]) / total,
            "gap_to_oracle": max(0.0, oracle - suppression),
        })

with open(out_csv, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["dataset", "cache", "capacity", "suppression_rate", "redundancy_rate", "eviction_pressure", "gap_to_oracle"])
    w.writeheader()
    w.writerows(rows)
PY

  generate_comparison_plots "$exp_root" "exp2" "$exp_root/flow_stats_summary.csv"
}

exp3_admission_study() {
  echo "[exp3] Admission study"

  local exp_root="$RESULTS_ROOT/exp3_admission"
  mkdir -p "$exp_root/csv" "$exp_root/plots"

  local exp34_temporal_sets=()
  while IFS= read -r ds; do
    [[ -n "$ds" ]] || continue
    exp34_temporal_sets+=("$ds")
  done < <(collect_exp34_temporal_sets)

  local admission_sets=(
    "$ANCHOR_DATASET"
    "${TOPOLOGY}_mono_burst_64"
    "${TOPOLOGY}_mono_256"
  )
  admission_sets+=("${exp34_temporal_sets[@]}")

  local ds
  for ds in "${admission_sets[@]}"; do
    ensure_dataset_log "$ds"
    ensure_route_csv "$ds"
    copy_csv_for_exp "$ds" "$exp_root/csv"
    plot_csv_if_missing "$(dataset_csv_path "$ds")" "$exp_root/plots" "results_synthetic_${ds}" "OneHitWonderLRU,PendingAdmissionLRU,PITCollapsedLRU,AdaptiveAdmissionLRU,OnlineAdaptiveAdmissionLRU,TimeLimitedBloomLRU,TinyLFULRU,TinyCacheLRU,LRU" "$ds"
  done

  write_flow_stats_summary "$exp_root/flow_stats_summary.csv" "$PROTOCOL" "${admission_sets[@]}"

  python3 - "$exp_root" <<'PY'
import csv
import glob
import os
import sys

exp_root = sys.argv[1]
out_csv = os.path.join(exp_root, "admission_deltas_vs_lru.csv")

tracked = {
    "OneHitWonderLRU",
    "PendingAdmissionLRU",
    "PITCollapsedLRU",
    "AdaptiveAdmissionLRU",
    "OnlineAdaptiveAdmissionLRU",
    "TimeLimitedBloomLRU",
    "TinyLFULRU",
    "TinyCacheLRU",
}

rows = []
for path in sorted(glob.glob(os.path.join(exp_root, "csv", "results_synthetic_*.csv"))):
    dataset = os.path.basename(path).replace("results_synthetic_", "").replace(".csv", "")
    by_cap = {}
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            cap = int(float(r["capacity"]))
            by_cap.setdefault(cap, {})[r["cache"]] = r

    for cap, group in sorted(by_cap.items()):
        if "LRU" not in group:
            continue
        lru = group["LRU"]
        lru_s = float(lru["suppression_rate"])
        lru_r = float(lru["redundancy_rate"])
        lru_e = float(lru["evictions"])
        for policy in sorted(tracked):
            if policy not in group:
                continue
            p = group[policy]
            ps = float(p["suppression_rate"])
            pr = float(p["redundancy_rate"])
            pe = float(p["evictions"])
            rows.append({
                "dataset": dataset,
                "capacity": cap,
                "cache": policy,
                "suppression_rate": ps,
                "redundancy_rate": pr,
                "evictions": int(pe),
                "suppression_gain_vs_lru": ps - lru_s,
                "redundancy_delta_vs_lru": pr - lru_r,
                "eviction_delta_vs_lru": pe - lru_e,
            })

with open(out_csv, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["dataset", "capacity", "cache", "suppression_rate", "redundancy_rate", "evictions", "suppression_gain_vs_lru", "redundancy_delta_vs_lru", "eviction_delta_vs_lru"])
    w.writeheader()
    w.writerows(rows)
PY

  generate_comparison_plots "$exp_root" "exp3" "$exp_root/flow_stats_summary.csv"
}

exp4_ttl_freshness_study() {
  echo "[exp4] TTL/freshness study"

  local exp_root="$RESULTS_ROOT/exp4_ttl_freshness"
  mkdir -p "$exp_root/csv" "$exp_root/plots"

  local exp34_temporal_sets=()
  while IFS= read -r ds; do
    [[ -n "$ds" ]] || continue
    exp34_temporal_sets+=("$ds")
  done < <(collect_exp34_temporal_sets)

  local ttl_sets=(
    "$ANCHOR_DATASET"
    "${TOPOLOGY}_mono_burst_64"
    "${TOPOLOGY}_mono_256"
  )
  ttl_sets+=("${exp34_temporal_sets[@]}")

  local ds
  for ds in "${ttl_sets[@]}"; do
    ensure_dataset_log "$ds"
    ensure_route_csv "$ds"
    copy_csv_for_exp "$ds" "$exp_root/csv"
    plot_csv_if_missing "$(dataset_csv_path "$ds")" "$exp_root/plots" "results_synthetic_${ds}" "LRUTtl(0.1ms),LRUTtl(0.5ms),LRUTtl(2ms),LRUTtl(10ms),FreshnessInvalidationLRU,CacheINTFreshnessLRU,FlowLifetimeAdaptiveTTL,LRU" "$ds"
  done

  write_flow_stats_summary "$exp_root/flow_stats_summary.csv" "$PROTOCOL" "${ttl_sets[@]}"

  python3 - "$exp_root" <<'PY'
import csv
import glob
import os
import sys

exp_root = sys.argv[1]
out_csv = os.path.join(exp_root, "ttl_freshness_summary.csv")

rows = []
for path in sorted(glob.glob(os.path.join(exp_root, "csv", "results_synthetic_*.csv"))):
    dataset = os.path.basename(path).replace("results_synthetic_", "").replace(".csv", "")
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            cache = r["cache"]
            if not (
                cache.startswith("LRUTtl(")
                or cache in {"FreshnessInvalidationLRU", "CacheINTFreshnessLRU", "FlowLifetimeAdaptiveTTL", "LRU"}
            ):
                continue
            total = max(1.0, float(r["total"]))
            forwards = max(1.0, float(r["forwards"]))
            rows.append({
                "dataset": dataset,
                "cache": cache,
                "capacity": int(float(r["capacity"])),
                "suppression_rate": float(r["suppression_rate"]),
                "redundancy_rate": float(r["redundancy_rate"]),
                "eviction_pressure": float(r["evictions"]) / total,
                "redundant_forward_share": float(r["redundant_forwards"]) / forwards,
            })

with open(out_csv, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["dataset", "cache", "capacity", "suppression_rate", "redundancy_rate", "eviction_pressure", "redundant_forward_share"])
    w.writeheader()
    w.writerows(rows)
PY

  generate_comparison_plots "$exp_root" "exp4" "$exp_root/flow_stats_summary.csv"
}

if run_exp 1; then exp1_workload_matrix; fi
if run_exp 2; then exp2_pressure_sweep; fi
if run_exp 3; then exp3_admission_study; fi
if run_exp 4; then exp4_ttl_freshness_study; fi

echo "Done. Selected experiments completed: ${SELECTED_EXPS[*]}"
