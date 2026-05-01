#!/usr/bin/env bash
set -euo pipefail

# End-to-end experiment runner.
# Reads fyp/dash_experiments/experiments.txt and runs each entry for 5 seeds:
#   htsim → flow stats → cache sim → temporal locality plot → flow distribution plot
# After all seeds complete for an entry, aggregates results into findings/.
#
# Usage: bash fyp/dash_scripts/run_experiments.sh [--parallel [--jobs N]] [--entry N]

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

EXPERIMENTS_FILE="fyp/dash_experiments/experiments.txt"
SCRIPTS="fyp/dash_scripts"
SEEDS=(42 67 1337 271828 314159)
ENTRY_FILTER=""
PARALLEL=""
MAX_JOBS=8   # max concurrent (entry,seed) leaf jobs; tuned for M1 Pro 8 P-cores

while [[ $# -gt 0 ]]; do
  case "$1" in
    --entry)
      [[ $# -ge 2 ]] || { echo "ERROR: --entry requires a value" >&2; exit 1; }
      ENTRY_FILTER="$2"; shift 2 ;;
    --parallel)
      PARALLEL=1; shift ;;
    --jobs)
      [[ $# -ge 2 ]] || { echo "ERROR: --jobs requires a value" >&2; exit 1; }
      MAX_JOBS="$2"; shift 2 ;;
    *)
      echo "ERROR: unknown argument: $1" >&2; exit 1 ;;
  esac
done

# Strip trailing _n and _<digits> from a dataset name to get its CM family.
# Matches schedule_experiments.py cm_family() logic.
cm_family() {
  local name="$1"
  name="${name%_n}"
  echo "$name" | sed 's/_[0-9][0-9]*$//'
}

# Map (protocol:dataset:context) → findings subdir
# Implemented as a function for bash 3.x compatibility (macOS ships bash 3.2, no declare -A)
obs_subdir() {
  local key="${1}:${2}:${3}"
  case "$key" in
    "ndp:incast_mono_n:route_changes")            echo "1_flow_size_sweep" ;;
    "ndp:incast_heavytail_burst_n:route_changes") echo "2_burst_sweep" ;;
    "ndp:incast_heavytail_sigma_n:route_changes") echo "3_skew_sweep" ;;
    "ndp:incast_heavytail:route_changes")         echo "4_source_seen_vs_route_change" ;;
    "ndp:incast_heavytail:source_seen")           echo "4_source_seen_vs_route_change" ;;
    "ndp:incast_heavytail_burst_1:route_changes")       echo "5_failure_mode_baselines" ;;
    "tcp:incast_heavytail:route_changes")               echo "5_failure_mode_baselines" ;;
    "tcp:a2a_heavytail:route_changes")                  echo "5_failure_mode_baselines" ;;
    "tcp:incast_heavytail_sigma_1p0:route_changes")     echo "5_failure_mode_baselines" ;;
    "ndp:incast_heavytail:congestion")            echo "7_congestion_incast_vs_a2a" ;;
    "ndp:a2a_heavytail:congestion")               echo "7_congestion_incast_vs_a2a" ;;
    "ndp:incast_heavytail_burst_8:route_changes") echo "8_policy_ranking" ;;
    "ndp:a2a_heavytail:route_changes")            echo "8_policy_ranking" ;;
    *)                                             echo "unknown" ;;
  esac
}

# Observation 6 (concurrent-flow threshold) reuses 1_flow_size_sweep data — no separate entry needed.

if [[ ! -f "$EXPERIMENTS_FILE" ]]; then
  echo "ERROR: experiments file not found: $EXPERIMENTS_FILE" >&2
  echo "       Run setup_dash_workspace.sh first, then populate experiments.txt" >&2
  exit 1
fi

ENTRIES=()
while IFS= read -r line; do
  ENTRIES+=("$line")
done < <(grep -v '^\s*#' "$EXPERIMENTS_FILE" | grep -v '^\s*$' || true)

if [[ ${#ENTRIES[@]} -eq 0 ]]; then
  echo "No entries found in $EXPERIMENTS_FILE — nothing to do."
  exit 0
fi

# ---------------------------------------------------------------------------
# --parallel mode: global (entry,seed) job pool with MAX_JOBS cap
# ---------------------------------------------------------------------------
if [[ -n "$PARALLEL" ]]; then
  LOG_DIR="fyp/dash_experiments/logs"
  mkdir -p "$LOG_DIR"

  # Build conflict key for each entry (0-based index)
  entry_keys=()
  for _entry in "${ENTRIES[@]}"; do
    read -r _proto _ds _ctx <<< "$_entry"
    entry_keys+=("${_proto}:$(cm_family "$_ds")")
  done

  # Global leaf-job pool (parallel arrays): one slot per running (entry,seed) job
  pool_pids=()
  pool_entry_nums=()   # 1-based entry number
  pool_run_idxs=()     # 1-based seed/run index
  pool_starts=()       # $SECONDS at launch
  pool_entry_keys=()   # conflict key of owning entry

  # Per-entry state (indexed by 0-based entry idx)
  # seeds_pending[i]  = space-separated list of run_idx values not yet launched for entry i
  # seeds_running[i]  = count of currently running seed jobs for entry i
  # seeds_done[i]     = count of finished seed jobs for entry i
  seeds_pending=()
  seeds_running=()
  seeds_done=()
  entry_starts=()  # $SECONDS when first seed of entry launched

  for i in "${!ENTRIES[@]}"; do
    seeds_pending+=("1 2 3 4 5")
    seeds_running+=("0")
    seeds_done+=("0")
    entry_starts+=("")
  done

  # pending_entries: indices of entries that still have seeds to launch
  pending_entries=()
  for i in "${!ENTRIES[@]}"; do pending_entries+=("$i"); done

  echo "=== Parallel runner: ${#ENTRIES[@]} entries × ${#SEEDS[@]} seeds (max ${MAX_JOBS} jobs) ==="

  # ── helper: reap any finished pool jobs ─────────────────────────────────
  reap_pool() {
    local new_pids=() new_entry_nums=() new_run_idxs=() new_starts=() new_keys=()
    local j
    for j in "${!pool_pids[@]}"; do
      if kill -0 "${pool_pids[$j]}" 2>/dev/null; then
        new_pids+=("${pool_pids[$j]}")
        new_entry_nums+=("${pool_entry_nums[$j]}")
        new_run_idxs+=("${pool_run_idxs[$j]}")
        new_starts+=("${pool_starts[$j]}")
        new_keys+=("${pool_entry_keys[$j]}")
      else
        wait "${pool_pids[$j]}" 2>/dev/null || true
        local en="${pool_entry_nums[$j]}"
        local ri="${pool_run_idxs[$j]}"
        local elapsed=$(( SECONDS - pool_starts[j] ))
        local idx=$((en - 1))
        echo "  [done]  entry ${en} run${ri} (${elapsed}s, finished $(date '+%H:%M:%S'))"
        seeds_running[$idx]=$(( seeds_running[idx] - 1 ))
        seeds_done[$idx]=$(( seeds_done[idx] + 1 ))
      fi
    done
    pool_pids=("${new_pids[@]+"${new_pids[@]}"}")
    pool_entry_nums=("${new_entry_nums[@]+"${new_entry_nums[@]}"}")
    pool_run_idxs=("${new_run_idxs[@]+"${new_run_idxs[@]}"}")
    pool_starts=("${new_starts[@]+"${new_starts[@]}"}")
    pool_entry_keys=("${new_keys[@]+"${new_keys[@]}"}")
  }

  # ── helper: set of conflict keys currently running ───────────────────────
  running_keys_set() {
    # prints one key per line
    local k
    for k in "${pool_entry_keys[@]+"${pool_entry_keys[@]}"}"; do
      echo "$k"
    done | sort -u
  }

  # ── helper: aggregate an entry once all 5 seeds are done ─────────────────
  aggregate_entry() {
    local idx="$1"
    local entry="${ENTRIES[$idx]}"
    read -r protocol dataset context <<< "$entry"
    local entry_num=$((idx + 1))
    echo ""
    echo "  [aggregate] entry ${entry_num}: collecting CSVs from 5 runs..."

    local findings_subdir
    findings_subdir="$(obs_subdir "$protocol" "$dataset" "$context")"
    if [[ "$findings_subdir" == "unknown" ]]; then
      echo "  WARN: no findings mapping for $protocol/$dataset/$context — aggregating to findings/unknown/"
    fi

    local findings_dir="fyp/dash_experiments/findings/${findings_subdir}"
    mkdir -p "$findings_dir"

    local csv_prefix
    case "$context" in
      route_changes) csv_prefix="results_synthetic_" ;;
      source_seen)   csv_prefix="results_synthetic_source_seen_" ;;
      congestion)    csv_prefix="results_synthetic_congestion_" ;;
    esac
    local ds_base="${dataset%_n}"
    local csv_glob
    if [[ "$dataset" == *_n ]]; then
      csv_glob="${csv_prefix}${ds_base}*.csv"
    else
      csv_glob="${csv_prefix}${ds_base}.csv"
    fi

    shopt -s nullglob
    local run1_csvs=(fyp/dash_experiments/run1/results/cache_sim/${context}/${protocol}/${csv_glob})
    shopt -u nullglob

    if [[ ${#run1_csvs[@]} -eq 0 ]]; then
      echo "  WARN: no result CSVs in run1/cache_sim/${context}/${protocol}/ matching ${csv_glob} — skipping"
      return
    fi

    local run1_csv csv_basename csv_inputs out_name output_csv
    for run1_csv in "${run1_csvs[@]}"; do
      csv_basename="$(basename "$run1_csv")"
      csv_inputs=()
      local i
      for i in 1 2 3 4 5; do
        local candidate="fyp/dash_experiments/run${i}/results/cache_sim/${context}/${protocol}/${csv_basename}"
        if [[ -f "$candidate" ]]; then
          csv_inputs+=("$candidate")
        else
          echo "  WARN: missing run${i} CSV: $candidate"
        fi
      done
      out_name="${csv_basename/results_synthetic_/mean_ci95_${protocol}_}"
      output_csv="${findings_dir}/${out_name}"
      echo "  [aggregate] $csv_basename → $output_csv (${#csv_inputs[@]} inputs)"
      if [[ ${#csv_inputs[@]} -eq 0 ]]; then
        echo "  WARN: no inputs found — skipping aggregate_runs.py"
        continue
      fi
      python3 "$SCRIPTS/aggregate_runs.py" \
        --inputs "${csv_inputs[@]}" \
        --output "$output_csv"
    done
    echo "  [aggregate] done for $protocol/$dataset/$context"
  }

  # ── main dispatch loop ────────────────────────────────────────────────────
  while true; do
    reap_pool

    # Check if everything is finished
    all_done=1
    for i in "${!ENTRIES[@]}"; do
      if [[ -n "${seeds_pending[$i]}" || "${seeds_running[$i]}" -gt 0 ]]; then
        all_done=0
        break
      fi
    done
    [[ $all_done -eq 1 ]] && break

    # Launch new seed jobs up to MAX_JOBS
    local_running_keys="$(running_keys_set)"

    new_pending_entries=()
    for i in "${pending_entries[@]+"${pending_entries[@]}"}"; do
      # Skip if no seeds left to launch for this entry
      if [[ -z "${seeds_pending[$i]}" ]]; then
        # Entry fully launched; may still have running seeds — keep until all done
        # (aggregate check below handles it)
        continue
      fi

      # Check conflict key
      ekey="${entry_keys[$i]}"
      if echo "$local_running_keys" | grep -qxF "$ekey"; then
        new_pending_entries+=("$i")
        continue
      fi

      # Launch as many seeds as the pool allows for this entry
      remaining="${seeds_pending[$i]}"
      new_remaining=""
      for run_idx in $remaining; do
        if [[ ${#pool_pids[@]} -ge $MAX_JOBS ]]; then
          # Pool full — defer remaining seeds
          new_remaining="${new_remaining:+$new_remaining }${run_idx}"
          continue
        fi

        seed="${SEEDS[$((run_idx - 1))]}"
        entry_num=$((i + 1))
        read -r protocol dataset context <<< "${ENTRIES[$i]}"

        # Record entry start time on first seed
        if [[ -z "${entry_starts[$i]}" ]]; then
          entry_starts[$i]="$SECONDS"
          echo "  [start] entry ${entry_num}: ${ENTRIES[$i]} ($(date '+%H:%M:%S'))"
        fi
        echo "  [start] entry ${entry_num} run${run_idx} seed=${seed} ($(date '+%H:%M:%S'))"

        (
          run_dir="fyp/dash_experiments/run${run_idx}"
          log_root="${run_dir}/dataset/raw_logs/${protocol}"
          log_file="${log_root}/log_${dataset}.txt"
          ds_log_prefix="${dataset%_n}"

          if [[ -s "$log_file" ]] || { [[ "$dataset" == *_n ]] && ls "${log_root}/log_${ds_log_prefix}"*.txt 2>/dev/null | grep -q .; }; then
            echo "  [run${run_idx}] [skip htsim] log exists"
          else
            echo "  [run${run_idx}] [htsim] running..."
            OUT_DIR="$log_root" \
            CM_DIR="${run_dir}/dataset/connection_matrices/${protocol}" \
              bash "$SCRIPTS/run_htsim_synthetic.sh" -p "$protocol" -d "$dataset" -s "$seed"
          fi

          echo "  [run${run_idx}] [flow stats] running..."
          OUT_DIR="${run_dir}/results/flow_stats/${protocol}" \
          LOG_ROOT="$log_root" \
            bash "$SCRIPTS/run_flow_stats_synthetic.sh" -p "$protocol" -d "$dataset"

          echo "  [run${run_idx}] [cache sim: $context] running..."
          cache_out="${run_dir}/results/cache_sim/${context}/${protocol}"
          case "$context" in
            route_changes)
              OUT_DIR="$cache_out" LOG_ROOT="$log_root" \
                bash "$SCRIPTS/run_cache_sim_synthetic.sh" -p "$protocol" -d "$dataset" ;;
            source_seen)
              OUT_DIR="$cache_out" LOG_ROOT="$log_root" \
                bash "$SCRIPTS/run_cache_sim_source_seen_synthetic.sh" -p "$protocol" -d "$dataset" ;;
            congestion)
              OUT_DIR="$cache_out" LOG_ROOT="$log_root" \
                bash "$SCRIPTS/run_cache_sim_congestion_synthetic.sh" -p "$protocol" -d "$dataset" ;;
          esac

          echo "  [run${run_idx}] [temporal locality plot] running..."
          OUT_DIR="${run_dir}/results/flow_concurrency/plots/${protocol}" \
          LOG_ROOT="$log_root" \
            bash "$SCRIPTS/run_plot_flow_concurrency_synthetic.sh" -p "$protocol" -d "$dataset"

          echo "  [run${run_idx}] [flow distribution plot] running..."
          OUT_DIR="${run_dir}/results/flow_size/plots/${protocol}" \
          LOG_ROOT="$log_root" \
            bash "$SCRIPTS/run_plot_flow_distribution_synthetic.sh" -p "$protocol" -d "$dataset"
        ) >> "${LOG_DIR}/entry_${entry_num}_run${run_idx}.log" 2>&1 &

        pool_pids+=($!)
        pool_entry_nums+=("$entry_num")
        pool_run_idxs+=("$run_idx")
        pool_starts+=("$SECONDS")
        pool_entry_keys+=("$ekey")
        seeds_running[$i]=$(( seeds_running[i] + 1 ))
        local_running_keys="$(echo "$local_running_keys"; echo "$ekey")"
      done

      seeds_pending[$i]="$new_remaining"
      # Keep in pending list if there are still seeds to launch
      if [[ -n "${seeds_pending[$i]}" ]]; then
        new_pending_entries+=("$i")
      fi
    done
    pending_entries=("${new_pending_entries[@]+"${new_pending_entries[@]}"}")

    # Aggregate any entries where all 5 seeds are now done
    for i in "${!ENTRIES[@]}"; do
      if [[ -z "${seeds_pending[$i]}" && "${seeds_running[$i]}" -eq 0 && "${seeds_done[$i]}" -eq 5 ]]; then
        # Mark as aggregated by setting done to sentinel 99
        if [[ "${seeds_done[$i]}" -eq 5 ]]; then
          aggregate_entry "$i"
          entry_num=$((i + 1))
          elapsed=$(( SECONDS - entry_starts[i] ))
          echo "  [done]  entry ${entry_num}: ${ENTRIES[$i]} (${elapsed}s total, finished $(date '+%H:%M:%S'))"
          seeds_done[$i]=99
        fi
      fi
    done

    [[ ${#pool_pids[@]} -gt 0 ]] && sleep 5
  done

  echo ""
  echo "=== All entries complete ==="
  exit 0
fi

# ---------------------------------------------------------------------------
# Sequential / single-entry mode (unchanged)
# ---------------------------------------------------------------------------
if [[ -n "$ENTRY_FILTER" ]]; then
  idx=$((ENTRY_FILTER - 1))
  if [[ $idx -lt 0 || $idx -ge ${#ENTRIES[@]} ]]; then
    echo "ERROR: --entry $ENTRY_FILTER out of range (1–${#ENTRIES[@]})" >&2; exit 1
  fi
  ENTRIES=("${ENTRIES[$idx]}")
  echo "=== Experiment runner: entry $ENTRY_FILTER only ==="
else
  echo "=== Experiment runner: ${#ENTRIES[@]} entries × ${#SEEDS[@]} seeds ==="
fi

for entry in "${ENTRIES[@]}"; do
  read -r protocol dataset context <<< "$entry"
  echo ""
  echo "======================================================================"
  echo " Entry: protocol=$protocol  dataset=$dataset  context=$context"
  echo "======================================================================"

  run_one_seed() {
    local run_idx="$1" seed="$2" protocol="$3" dataset="$4" context="$5"
    local run_dir="fyp/dash_experiments/run${run_idx}"
    local log_root="${run_dir}/dataset/raw_logs/${protocol}"
    local log_file="${log_root}/log_${dataset}.txt"
    local ds_log_prefix="${dataset%_n}"

    echo "--- run${run_idx} / seed=${seed} ---"

    # 1. htsim (skip if non-empty log already exists)
    if [[ -s "$log_file" ]] || { [[ "$dataset" == *_n ]] && ls "${log_root}/log_${ds_log_prefix}"*.txt 2>/dev/null | grep -q .; }; then
      echo "  [run${run_idx}] [skip htsim] log exists"
    else
      echo "  [run${run_idx}] [htsim] running..."
      OUT_DIR="$log_root" \
      CM_DIR="${run_dir}/dataset/connection_matrices/${protocol}" \
        bash "$SCRIPTS/run_htsim_synthetic.sh" -p "$protocol" -d "$dataset" -s "$seed"
    fi

    # 2. flow stats
    echo "  [run${run_idx}] [flow stats] running..."
    OUT_DIR="${run_dir}/results/flow_stats/${protocol}" \
    LOG_ROOT="$log_root" \
      bash "$SCRIPTS/run_flow_stats_synthetic.sh" -p "$protocol" -d "$dataset"

    # 3. cache sim
    echo "  [run${run_idx}] [cache sim: $context] running..."
    local cache_out="${run_dir}/results/cache_sim/${context}/${protocol}"
    case "$context" in
      route_changes)
        OUT_DIR="$cache_out" LOG_ROOT="$log_root" \
          bash "$SCRIPTS/run_cache_sim_synthetic.sh" -p "$protocol" -d "$dataset"
        ;;
      source_seen)
        OUT_DIR="$cache_out" LOG_ROOT="$log_root" \
          bash "$SCRIPTS/run_cache_sim_source_seen_synthetic.sh" -p "$protocol" -d "$dataset"
        ;;
      congestion)
        OUT_DIR="$cache_out" LOG_ROOT="$log_root" \
          bash "$SCRIPTS/run_cache_sim_congestion_synthetic.sh" -p "$protocol" -d "$dataset"
        ;;
      *)
        echo "  ERROR: unknown context '$context'" >&2; return 1 ;;
    esac

    # 4. temporal locality plot
    echo "  [run${run_idx}] [temporal locality plot] running..."
    OUT_DIR="${run_dir}/results/flow_concurrency/plots/${protocol}" \
    LOG_ROOT="$log_root" \
      bash "$SCRIPTS/run_plot_flow_concurrency_synthetic.sh" -p "$protocol" -d "$dataset"

    # 5. flow distribution plot
    echo "  [run${run_idx}] [flow distribution plot] running..."
    OUT_DIR="${run_dir}/results/flow_size/plots/${protocol}" \
    LOG_ROOT="$log_root" \
      bash "$SCRIPTS/run_plot_flow_distribution_synthetic.sh" -p "$protocol" -d "$dataset"

    echo "  [run${run_idx}] done."
  }

  seed_pids=()
  run_idx=0
  for seed in "${SEEDS[@]}"; do
    run_idx=$((run_idx + 1))
    run_one_seed "$run_idx" "$seed" "$protocol" "$dataset" "$context" &
    seed_pids+=($!)
  done
  echo "  [seeds] launched ${#seed_pids[@]} parallel seed jobs, waiting..."
  for pid in "${seed_pids[@]}"; do
    wait "$pid" || { echo "  ERROR: seed job (pid=$pid) failed" >&2; exit 1; }
  done
  echo "  [seeds] all done."

  # 6. Aggregate across all 5 runs → findings
  echo ""
  echo "  [aggregate] collecting CSVs from 5 runs..."

  findings_subdir="$(obs_subdir "$protocol" "$dataset" "$context")"

  if [[ "$findings_subdir" == "unknown" ]]; then
    echo "  WARN: no findings mapping for $protocol/$dataset/$context — aggregating to findings/unknown/"
  fi

  findings_dir="fyp/dash_experiments/findings/${findings_subdir}"
  mkdir -p "$findings_dir"

  case "$context" in
    route_changes) csv_prefix="results_synthetic_" ;;
    source_seen)   csv_prefix="results_synthetic_source_seen_" ;;
    congestion)    csv_prefix="results_synthetic_congestion_" ;;
  esac
  ds_base="${dataset%_n}"
  if [[ "$dataset" == *_n ]]; then
    csv_glob="${csv_prefix}${ds_base}*.csv"
  else
    csv_glob="${csv_prefix}${ds_base}.csv"
  fi
  shopt -s nullglob
  run1_csvs=(fyp/dash_experiments/run1/results/cache_sim/${context}/${protocol}/${csv_glob})
  shopt -u nullglob

  if [[ ${#run1_csvs[@]} -eq 0 ]]; then
    echo "  WARN: no result CSVs found in run1/cache_sim/${context}/${protocol}/ matching ${csv_glob} — skipping aggregation"
    continue
  fi

  for run1_csv in "${run1_csvs[@]}"; do
    csv_basename="$(basename "$run1_csv")"
    csv_inputs=()
    all_found=1
    for i in 1 2 3 4 5; do
      candidate="fyp/dash_experiments/run${i}/results/cache_sim/${context}/${protocol}/${csv_basename}"
      if [[ -f "$candidate" ]]; then
        csv_inputs+=("$candidate")
      else
        echo "  WARN: missing run${i} CSV: $candidate"
        all_found=0
      fi
    done

    out_name="${csv_basename/results_synthetic_/mean_ci95_${protocol}_}"
    output_csv="${findings_dir}/${out_name}"

    echo "  [aggregate] $csv_basename → $output_csv (${#csv_inputs[@]} inputs)"
    if [[ ${#csv_inputs[@]} -eq 0 ]]; then
      echo "  WARN: no inputs found for $csv_basename — skipping aggregate_runs.py"
      continue
    fi
    python3 "$SCRIPTS/aggregate_runs.py" \
      --inputs "${csv_inputs[@]}" \
      --output "$output_csv"
  done

  echo "  [aggregate] done for $protocol/$dataset/$context"
done

echo ""
echo "=== All experiments complete ==="
