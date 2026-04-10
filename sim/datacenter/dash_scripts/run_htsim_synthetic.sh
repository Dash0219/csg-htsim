#!/usr/bin/env bash
set -euo pipefail

print_usage() {
  cat <<'EOF'
Usage:
  bash dash_scripts/run_htsim_synthetic.sh [options]

Options:
  -d, --dataset NAME        Run one dataset family (example: a2a_pareto)
  -l, --low-temp-locality   Generate only low-temp-locality datasets
  -s, --seed N              Random seed for matrix generators (default: current epoch seconds)
  -h, --help           Show this help

Environment variables:
  LOW_TEMP_LOCALITY    Equivalent to --low-temp-locality (0/1)
  SEED                 Equivalent to --seed
  DATASET              Equivalent to --dataset
  TARGET_PATTERN       Deprecated legacy alias for DATASET
  GENERATE_LOW_TEMP_LOCALITY  Deprecated legacy alias for LOW_TEMP_LOCALITY
EOF
}

DATASET="${DATASET:-}"
TARGET_PATTERN="${TARGET_PATTERN:-}"
LOW_TEMP_LOCALITY="${LOW_TEMP_LOCALITY:-}"
SEED="${SEED:-}"

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
    -s|--seed)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --seed requires a value" >&2
        exit 1
      fi
      SEED="$2"
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

if [[ -z "$DATASET" && -n "$TARGET_PATTERN" ]]; then
  DATASET="$TARGET_PATTERN"
  echo "WARN: TARGET_PATTERN is deprecated; use --dataset (or DATASET) instead." >&2
elif [[ -n "$DATASET" && -n "$TARGET_PATTERN" && "$DATASET" != "$TARGET_PATTERN" ]]; then
  echo "ERROR: DATASET ($DATASET) and TARGET_PATTERN ($TARGET_PATTERN) disagree" >&2
  exit 1
fi

if [[ -z "$LOW_TEMP_LOCALITY" && -n "${GENERATE_LOW_TEMP_LOCALITY+x}" ]]; then
  LOW_TEMP_LOCALITY="${GENERATE_LOW_TEMP_LOCALITY}"
  echo "WARN: GENERATE_LOW_TEMP_LOCALITY is deprecated; use --low-temp-locality (or LOW_TEMP_LOCALITY=1)." >&2
fi

# Generate synthetic INT logs using HTSIM NDP runs.
# Dataset logs below are stderr-only (INT traces).
# Stdout progress/debug output is written to dash_results/synthetic/raw_logs/*.raw.log.
# Output files are written to:
#   dash_dataset/synthetic/log_incast_mono.txt
#   dash_dataset/synthetic/log_a2a_mono.txt
#   dash_dataset/synthetic/log_incast_bimodal.txt
#   dash_dataset/synthetic/log_a2a_bimodal.txt
#   dash_dataset/synthetic/log_incast_pareto.txt
#   dash_dataset/synthetic/log_a2a_pareto.txt
#   dash_dataset/synthetic/log_incast_pareto_heavy.txt
#   dash_dataset/synthetic/log_a2a_pareto_heavy.txt
#   dash_dataset/synthetic/log_incast_lognormal_skewed.txt
#   dash_dataset/synthetic/log_a2a_lognormal_skewed.txt
#   dash_dataset/synthetic/log_incast_exponential_skewed.txt
#   dash_dataset/synthetic/log_a2a_exponential_skewed.txt
# Optional low-temporal-locality variants (suffix defaults to _low_temp_locality):
#   dash_dataset/synthetic/log_<pattern>_low_temp_locality.txt

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -x "./htsim_ndp" ]]; then
  echo "ERROR: ./htsim_ndp not found or not executable. Build first with: make all"
  exit 1
fi

OUT_DIR="dash_dataset/synthetic"
CM_DIR="dash_results/synthetic/connection_matrices"
RUN_DIR="dash_results/synthetic/raw_logs"

mkdir -p "$OUT_DIR" "$CM_DIR" "$RUN_DIR"

NODES="${NODES:-1024}"
CONNS_INCAST="${CONNS_INCAST:-512}"
FLOWSIZE_INCAST="${FLOWSIZE_INCAST:-10000000}"
# Keep start spread tight by default to preserve high flow overlap.
EXTRA_START_US="${EXTRA_START_US:-0}"
if [[ -z "${SEED}" ]]; then
  # Default to a non-deterministic seed unless explicitly overridden.
  SEED="$(date +%s)"
fi
# Unified per-shape run durations. Keep incast longer, A2A shorter by default.
END_US_INCAST="${END_US_INCAST:-1000000000}"
END_US_A2A="${END_US_A2A:-1000}"
ROUTE_STRAT="${ROUTE_STRAT:-perm}"
NDP_PATHS="${NDP_PATHS:-8}"
NDP_PATH_BURST="${NDP_PATH_BURST:-64}"

A2A_CONNS="${A2A_CONNS:-512}"
A2A_GROUPSIZE="${A2A_GROUPSIZE:-512}"
A2A_PARALLEL="${A2A_PARALLEL:-64}"
FLOWSIZE_A2A="${FLOWSIZE_A2A:-1000000}"
EXTRA_START_US_A2A="${EXTRA_START_US_A2A:-0}"

BIMODAL_SPEC="${BIMODAL_SPEC:-bimodal:0.9:1:10000000}"
PARETO_SPEC="${PARETO_SPEC:-pareto:800:1.1:20000000}"

# Additional skewed distributions
PARETO_HEAVY_SPEC="${PARETO_HEAVY_SPEC:-pareto:800:0.8:50000000}"
LOGNORMAL_SKEWED_SPEC="${LOGNORMAL_SKEWED_SPEC:-lognormal:0.0:1.2:1460:50000000}"
EXPONENTIAL_SKEWED_SPEC="${EXPONENTIAL_SKEWED_SPEC:-exponential:200000:50000000}"

# Low-temp-specific size distributions. These increase flow churn while allowing
# concurrency to stay close to the normal profile (same parallelism/start spread).
LOW_PARETO_SPEC="${LOW_PARETO_SPEC:-pareto:64:1.1:2000000}"
LOW_PARETO_HEAVY_SPEC="${LOW_PARETO_HEAVY_SPEC:-pareto:64:0.8:5000000}"

# Optional low-temporal-locality variants (disabled by default).
LOW_TEMP_LOCALITY="${LOW_TEMP_LOCALITY:-0}"
LOW_TEMP_SUFFIX="${LOW_TEMP_SUFFIX:-low_temp_locality}"
LOW_EXTRA_START_US="${LOW_EXTRA_START_US:-$EXTRA_START_US}"
LOW_EXTRA_START_US_A2A="${LOW_EXTRA_START_US_A2A:-$EXTRA_START_US_A2A}"
LOW_A2A_PARALLEL="${LOW_A2A_PARALLEL:-$A2A_PARALLEL}"
LOW_FLOWSIZE_A2A="${LOW_FLOWSIZE_A2A:-20000}"
LOW_END_US_INCAST="${LOW_END_US_INCAST:-$END_US_INCAST}"
LOW_END_US_A2A="${LOW_END_US_A2A:-$END_US_A2A}"

if [[ "$LOW_TEMP_LOCALITY" != "0" && "$LOW_TEMP_LOCALITY" != "1" ]]; then
  echo "ERROR: LOW_TEMP_LOCALITY must be 0 or 1" >&2
  exit 1
fi

is_low_dataset_name() {
  local name="$1"
  [[ "$name" == *"_${LOW_TEMP_SUFFIX}" ]]
}

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

is_valid_dataset() {
  local name="$1"
  case "$name" in
    incast_mono|a2a_mono|incast_bimodal|a2a_bimodal|incast_pareto|a2a_pareto|incast_pareto_heavy|a2a_pareto_heavy|incast_lognormal_skewed|a2a_lognormal_skewed|incast_exponential_skewed|a2a_exponential_skewed)
      return 0
      ;;
    incast_mono_"$LOW_TEMP_SUFFIX"|a2a_mono_"$LOW_TEMP_SUFFIX"|incast_bimodal_"$LOW_TEMP_SUFFIX"|a2a_bimodal_"$LOW_TEMP_SUFFIX"|incast_pareto_"$LOW_TEMP_SUFFIX"|a2a_pareto_"$LOW_TEMP_SUFFIX"|incast_pareto_heavy_"$LOW_TEMP_SUFFIX"|a2a_pareto_heavy_"$LOW_TEMP_SUFFIX"|incast_lognormal_skewed_"$LOW_TEMP_SUFFIX"|a2a_lognormal_skewed_"$LOW_TEMP_SUFFIX"|incast_exponential_skewed_"$LOW_TEMP_SUFFIX"|a2a_exponential_skewed_"$LOW_TEMP_SUFFIX")
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

if [[ -n "$DATASET" ]] && ! is_valid_dataset "$DATASET"; then
  echo "ERROR: unknown dataset '$DATASET'" >&2
  echo "Run with --help to see accepted naming patterns." >&2
  exit 1
fi

INC_CM="$CM_DIR/incast_mono_fixed.cm"
A2A_CM="$CM_DIR/a2a_mono.cm"
INCAST_BIMODAL_CM="$CM_DIR/incast_bimodal.cm"
A2A_BIMODAL_CM="$CM_DIR/a2a_bimodal.cm"
INCAST_PARETO_CM="$CM_DIR/incast_pareto.cm"
A2A_PARETO_CM="$CM_DIR/a2a_pareto.cm"
INCAST_PARETO_HEAVY_CM="$CM_DIR/incast_pareto_heavy.cm"
A2A_PARETO_HEAVY_CM="$CM_DIR/a2a_pareto_heavy.cm"
INCAST_LOGNORMAL_SKEWED_CM="$CM_DIR/incast_lognormal_skewed.cm"
A2A_LOGNORMAL_SKEWED_CM="$CM_DIR/a2a_lognormal_skewed.cm"
INCAST_EXPONENTIAL_SKEWED_CM="$CM_DIR/incast_exponential_skewed.cm"
A2A_EXPONENTIAL_SKEWED_CM="$CM_DIR/a2a_exponential_skewed.cm"

echo "== Synthetic config =="
echo "NODES=$NODES CONNS_INCAST=$CONNS_INCAST FLOWSIZE_INCAST=$FLOWSIZE_INCAST EXTRA_START_US=$EXTRA_START_US"
echo "A2A_CONNS=$A2A_CONNS A2A_GROUPSIZE=$A2A_GROUPSIZE A2A_PARALLEL=$A2A_PARALLEL FLOWSIZE_A2A=$FLOWSIZE_A2A EXTRA_START_US_A2A=$EXTRA_START_US_A2A"
echo "ROUTE_STRAT=$ROUTE_STRAT NDP_PATHS=$NDP_PATHS NDP_PATH_BURST=$NDP_PATH_BURST END_US_INCAST=$END_US_INCAST END_US_A2A=$END_US_A2A SEED=$SEED"
echo "DATASET=${DATASET:-<all>} LOW_TEMP_LOCALITY=$LOW_TEMP_LOCALITY LOW_TEMP_SUFFIX=$LOW_TEMP_SUFFIX"
echo "LOW_EXTRA_START_US=$LOW_EXTRA_START_US LOW_EXTRA_START_US_A2A=$LOW_EXTRA_START_US_A2A LOW_A2A_PARALLEL=$LOW_A2A_PARALLEL LOW_FLOWSIZE_A2A=$LOW_FLOWSIZE_A2A LOW_END_US_INCAST=$LOW_END_US_INCAST LOW_END_US_A2A=$LOW_END_US_A2A"
echo "LOW_PARETO_SPEC=$LOW_PARETO_SPEC LOW_PARETO_HEAVY_SPEC=$LOW_PARETO_HEAVY_SPEC"
echo

run_gen() {
  "$@" >/dev/null
}

TOTAL_WRITTEN_LINES=0

should_process() {
  local name="$1"
  if [[ "$LOW_TEMP_LOCALITY" == "1" ]]; then
    is_low_dataset_name "$name" || return 1
  else
    is_low_dataset_name "$name" && return 1
  fi
  [[ -z "$DATASET" || "$DATASET" == "$name" ]]
}

echo "== Generating traffic matrices =="
if should_process "incast_mono"; then
  run_gen python3 connection_matrices/gen_incast.py "$INC_CM" "$NODES" "$CONNS_INCAST" "$FLOWSIZE_INCAST" "$EXTRA_START_US" "$SEED" fixed
fi
if (( A2A_GROUPSIZE <= 0 || A2A_CONNS <= 0 )); then
  echo "ERROR: A2A_GROUPSIZE and A2A_CONNS must be > 0"
  exit 1
fi
if (( A2A_CONNS % A2A_GROUPSIZE != 0 )); then
  echo "ERROR: A2A_CONNS ($A2A_CONNS) must be a multiple of A2A_GROUPSIZE ($A2A_GROUPSIZE)"
  exit 1
fi
if (( A2A_PARALLEL <= 0 || A2A_PARALLEL > A2A_GROUPSIZE - 1 )); then
  echo "ERROR: A2A_PARALLEL must be in [1, A2A_GROUPSIZE-1]"
  exit 1
fi
if (( LOW_A2A_PARALLEL <= 0 || LOW_A2A_PARALLEL > A2A_GROUPSIZE - 1 )); then
  echo "ERROR: LOW_A2A_PARALLEL must be in [1, A2A_GROUPSIZE-1]"
  exit 1
fi
if should_process "a2a_mono"; then
  if (( A2A_PARALLEL == 1 )); then
    run_gen python3 connection_matrices/gen_serial_alltoall.py "$A2A_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$FLOWSIZE_A2A" "$EXTRA_START_US_A2A" "$SEED"
  else
    run_gen python3 connection_matrices/gen_serialn_alltoall.py "$A2A_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$A2A_PARALLEL" "$FLOWSIZE_A2A" "$EXTRA_START_US_A2A" "$SEED"
  fi
fi

if should_process "incast_bimodal"; then
  run_gen python3 connection_matrices/gen_incast.py "$INCAST_BIMODAL_CM" "$NODES" "$CONNS_INCAST" "$FLOWSIZE_INCAST" "$EXTRA_START_US" "$SEED" "$BIMODAL_SPEC"
fi
if should_process "incast_pareto"; then
  run_gen python3 connection_matrices/gen_incast.py "$INCAST_PARETO_CM" "$NODES" "$CONNS_INCAST" "$FLOWSIZE_INCAST" "$EXTRA_START_US" "$SEED" "$PARETO_SPEC"
fi
if should_process "incast_pareto_heavy"; then
  run_gen python3 connection_matrices/gen_incast.py "$INCAST_PARETO_HEAVY_CM" "$NODES" "$CONNS_INCAST" "$FLOWSIZE_INCAST" "$EXTRA_START_US" "$SEED" "$PARETO_HEAVY_SPEC"
fi
if should_process "incast_lognormal_skewed"; then
  run_gen python3 connection_matrices/gen_incast.py "$INCAST_LOGNORMAL_SKEWED_CM" "$NODES" "$CONNS_INCAST" "$FLOWSIZE_INCAST" "$EXTRA_START_US" "$SEED" "$LOGNORMAL_SKEWED_SPEC"
fi
if should_process "incast_exponential_skewed"; then
  run_gen python3 connection_matrices/gen_incast.py "$INCAST_EXPONENTIAL_SKEWED_CM" "$NODES" "$CONNS_INCAST" "$FLOWSIZE_INCAST" "$EXTRA_START_US" "$SEED" "$EXPONENTIAL_SKEWED_SPEC"
fi

if (( A2A_PARALLEL == 1 )); then
  if should_process "a2a_bimodal"; then
    run_gen python3 connection_matrices/gen_serial_alltoall.py "$A2A_BIMODAL_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$FLOWSIZE_A2A" "$EXTRA_START_US_A2A" "$SEED" "$BIMODAL_SPEC"
  fi
  if should_process "a2a_pareto"; then
    run_gen python3 connection_matrices/gen_serial_alltoall.py "$A2A_PARETO_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$FLOWSIZE_A2A" "$EXTRA_START_US_A2A" "$SEED" "$PARETO_SPEC"
  fi
  if should_process "a2a_pareto_heavy"; then
    run_gen python3 connection_matrices/gen_serial_alltoall.py "$A2A_PARETO_HEAVY_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$FLOWSIZE_A2A" "$EXTRA_START_US_A2A" "$SEED" "$PARETO_HEAVY_SPEC"
  fi
  if should_process "a2a_lognormal_skewed"; then
    run_gen python3 connection_matrices/gen_serial_alltoall.py "$A2A_LOGNORMAL_SKEWED_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$FLOWSIZE_A2A" "$EXTRA_START_US_A2A" "$SEED" "$LOGNORMAL_SKEWED_SPEC"
  fi
  if should_process "a2a_exponential_skewed"; then
    run_gen python3 connection_matrices/gen_serial_alltoall.py "$A2A_EXPONENTIAL_SKEWED_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$FLOWSIZE_A2A" "$EXTRA_START_US_A2A" "$SEED" "$EXPONENTIAL_SKEWED_SPEC"
  fi
else
  if should_process "a2a_bimodal"; then
    run_gen python3 connection_matrices/gen_serialn_alltoall.py "$A2A_BIMODAL_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$A2A_PARALLEL" "$FLOWSIZE_A2A" "$EXTRA_START_US_A2A" "$SEED" "$BIMODAL_SPEC"
  fi
  if should_process "a2a_pareto"; then
    run_gen python3 connection_matrices/gen_serialn_alltoall.py "$A2A_PARETO_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$A2A_PARALLEL" "$FLOWSIZE_A2A" "$EXTRA_START_US_A2A" "$SEED" "$PARETO_SPEC"
  fi
  if should_process "a2a_pareto_heavy"; then
    run_gen python3 connection_matrices/gen_serialn_alltoall.py "$A2A_PARETO_HEAVY_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$A2A_PARALLEL" "$FLOWSIZE_A2A" "$EXTRA_START_US_A2A" "$SEED" "$PARETO_HEAVY_SPEC"
  fi
  if should_process "a2a_lognormal_skewed"; then
    run_gen python3 connection_matrices/gen_serialn_alltoall.py "$A2A_LOGNORMAL_SKEWED_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$A2A_PARALLEL" "$FLOWSIZE_A2A" "$EXTRA_START_US_A2A" "$SEED" "$LOGNORMAL_SKEWED_SPEC"
  fi
  if should_process "a2a_exponential_skewed"; then
    run_gen python3 connection_matrices/gen_serialn_alltoall.py "$A2A_EXPONENTIAL_SKEWED_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$A2A_PARALLEL" "$FLOWSIZE_A2A" "$EXTRA_START_US_A2A" "$SEED" "$EXPONENTIAL_SKEWED_SPEC"
  fi
fi

run_ndp() {
  local name="$1"
  local cm_file="$2"
  local conns="$3"
  local end_us="${4:-$END_US_INCAST}"
  local out_file="$OUT_DIR/log_${name}.txt"
  local raw_file="$RUN_DIR/${name}.raw.log"

  if ! should_process "$name"; then
    return
  fi
  if [[ ! -f "$cm_file" ]]; then
    echo "Skipping ${name}: missing matrix ${cm_file}"
    return
  fi

  echo "== Running HTSIM NDP for ${name}; writing to ${out_file} =="
  ./htsim_ndp -nodes "$NODES" -conns "$conns" -tm "$cm_file" -strat "$ROUTE_STRAT" -paths "$NDP_PATHS" -path_burst "$NDP_PATH_BURST" -end "$end_us" 1> "$raw_file" 2> "$out_file"

  local line_count
  line_count=$(wc -l < "$out_file" | tr -d '[:space:]')
  TOTAL_WRITTEN_LINES=$((TOTAL_WRITTEN_LINES + line_count))
  echo "Wrote (${line_count} lines)"
}

run_ndp "incast_mono" "$INC_CM" "$CONNS_INCAST"
run_ndp "a2a_mono" "$A2A_CM" "$A2A_CONNS" "$END_US_A2A"
run_ndp "incast_bimodal" "$INCAST_BIMODAL_CM" "$CONNS_INCAST"
run_ndp "a2a_bimodal" "$A2A_BIMODAL_CM" "$A2A_CONNS" "$END_US_A2A"
run_ndp "incast_pareto" "$INCAST_PARETO_CM" "$CONNS_INCAST"
run_ndp "a2a_pareto" "$A2A_PARETO_CM" "$A2A_CONNS" "$END_US_A2A"
run_ndp "incast_pareto_heavy" "$INCAST_PARETO_HEAVY_CM" "$CONNS_INCAST"
run_ndp "a2a_pareto_heavy" "$A2A_PARETO_HEAVY_CM" "$A2A_CONNS" "$END_US_A2A"
run_ndp "incast_lognormal_skewed" "$INCAST_LOGNORMAL_SKEWED_CM" "$CONNS_INCAST"
run_ndp "a2a_lognormal_skewed" "$A2A_LOGNORMAL_SKEWED_CM" "$A2A_CONNS" "$END_US_A2A"
run_ndp "incast_exponential_skewed" "$INCAST_EXPONENTIAL_SKEWED_CM" "$CONNS_INCAST"
run_ndp "a2a_exponential_skewed" "$A2A_EXPONENTIAL_SKEWED_CM" "$A2A_CONNS" "$END_US_A2A"

if [[ "$LOW_TEMP_LOCALITY" == "1" ]]; then
  echo
  echo "== Generating low-temporal-locality matrices =="

  INC_LOW_CM="$CM_DIR/incast_mono_${LOW_TEMP_SUFFIX}.cm"
  A2A_LOW_CM="$CM_DIR/a2a_mono_${LOW_TEMP_SUFFIX}.cm"
  INCAST_BIMODAL_LOW_CM="$CM_DIR/incast_bimodal_${LOW_TEMP_SUFFIX}.cm"
  A2A_BIMODAL_LOW_CM="$CM_DIR/a2a_bimodal_${LOW_TEMP_SUFFIX}.cm"
  INCAST_PARETO_LOW_CM="$CM_DIR/incast_pareto_${LOW_TEMP_SUFFIX}.cm"
  A2A_PARETO_LOW_CM="$CM_DIR/a2a_pareto_${LOW_TEMP_SUFFIX}.cm"
  INCAST_PARETO_HEAVY_LOW_CM="$CM_DIR/incast_pareto_heavy_${LOW_TEMP_SUFFIX}.cm"
  A2A_PARETO_HEAVY_LOW_CM="$CM_DIR/a2a_pareto_heavy_${LOW_TEMP_SUFFIX}.cm"
  INCAST_LOGNORMAL_SKEWED_LOW_CM="$CM_DIR/incast_lognormal_skewed_${LOW_TEMP_SUFFIX}.cm"
  A2A_LOGNORMAL_SKEWED_LOW_CM="$CM_DIR/a2a_lognormal_skewed_${LOW_TEMP_SUFFIX}.cm"
  INCAST_EXPONENTIAL_SKEWED_LOW_CM="$CM_DIR/incast_exponential_skewed_${LOW_TEMP_SUFFIX}.cm"
  A2A_EXPONENTIAL_SKEWED_LOW_CM="$CM_DIR/a2a_exponential_skewed_${LOW_TEMP_SUFFIX}.cm"

  if should_process "incast_mono_${LOW_TEMP_SUFFIX}"; then
    run_gen python3 connection_matrices/gen_incast.py "$INC_LOW_CM" "$NODES" "$CONNS_INCAST" "$FLOWSIZE_INCAST" "$LOW_EXTRA_START_US" "$SEED" fixed
  fi
  if should_process "a2a_mono_${LOW_TEMP_SUFFIX}"; then
    if (( LOW_A2A_PARALLEL == 1 )); then
      run_gen python3 connection_matrices/gen_serial_alltoall.py "$A2A_LOW_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$LOW_FLOWSIZE_A2A" "$LOW_EXTRA_START_US_A2A" "$SEED"
    else
      run_gen python3 connection_matrices/gen_serialn_alltoall.py "$A2A_LOW_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$LOW_A2A_PARALLEL" "$LOW_FLOWSIZE_A2A" "$LOW_EXTRA_START_US_A2A" "$SEED"
    fi
  fi

  if should_process "incast_bimodal_${LOW_TEMP_SUFFIX}"; then
    run_gen python3 connection_matrices/gen_incast.py "$INCAST_BIMODAL_LOW_CM" "$NODES" "$CONNS_INCAST" "$FLOWSIZE_INCAST" "$LOW_EXTRA_START_US" "$SEED" "$BIMODAL_SPEC"
  fi
  if should_process "incast_pareto_${LOW_TEMP_SUFFIX}"; then
    run_gen python3 connection_matrices/gen_incast.py "$INCAST_PARETO_LOW_CM" "$NODES" "$CONNS_INCAST" "$FLOWSIZE_INCAST" "$LOW_EXTRA_START_US" "$SEED" "$LOW_PARETO_SPEC"
  fi
  if should_process "incast_pareto_heavy_${LOW_TEMP_SUFFIX}"; then
    run_gen python3 connection_matrices/gen_incast.py "$INCAST_PARETO_HEAVY_LOW_CM" "$NODES" "$CONNS_INCAST" "$FLOWSIZE_INCAST" "$LOW_EXTRA_START_US" "$SEED" "$LOW_PARETO_HEAVY_SPEC"
  fi
  if should_process "incast_lognormal_skewed_${LOW_TEMP_SUFFIX}"; then
    run_gen python3 connection_matrices/gen_incast.py "$INCAST_LOGNORMAL_SKEWED_LOW_CM" "$NODES" "$CONNS_INCAST" "$FLOWSIZE_INCAST" "$LOW_EXTRA_START_US" "$SEED" "$LOGNORMAL_SKEWED_SPEC"
  fi
  if should_process "incast_exponential_skewed_${LOW_TEMP_SUFFIX}"; then
    run_gen python3 connection_matrices/gen_incast.py "$INCAST_EXPONENTIAL_SKEWED_LOW_CM" "$NODES" "$CONNS_INCAST" "$FLOWSIZE_INCAST" "$LOW_EXTRA_START_US" "$SEED" "$EXPONENTIAL_SKEWED_SPEC"
  fi

  if (( LOW_A2A_PARALLEL == 1 )); then
    if should_process "a2a_bimodal_${LOW_TEMP_SUFFIX}"; then
      run_gen python3 connection_matrices/gen_serial_alltoall.py "$A2A_BIMODAL_LOW_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$LOW_FLOWSIZE_A2A" "$LOW_EXTRA_START_US_A2A" "$SEED" "$BIMODAL_SPEC"
    fi
    if should_process "a2a_pareto_${LOW_TEMP_SUFFIX}"; then
      run_gen python3 connection_matrices/gen_serial_alltoall.py "$A2A_PARETO_LOW_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$LOW_FLOWSIZE_A2A" "$LOW_EXTRA_START_US_A2A" "$SEED" "$LOW_PARETO_SPEC"
    fi
    if should_process "a2a_pareto_heavy_${LOW_TEMP_SUFFIX}"; then
      run_gen python3 connection_matrices/gen_serial_alltoall.py "$A2A_PARETO_HEAVY_LOW_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$LOW_FLOWSIZE_A2A" "$LOW_EXTRA_START_US_A2A" "$SEED" "$LOW_PARETO_HEAVY_SPEC"
    fi
    if should_process "a2a_lognormal_skewed_${LOW_TEMP_SUFFIX}"; then
      run_gen python3 connection_matrices/gen_serial_alltoall.py "$A2A_LOGNORMAL_SKEWED_LOW_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$LOW_FLOWSIZE_A2A" "$LOW_EXTRA_START_US_A2A" "$SEED" "$LOGNORMAL_SKEWED_SPEC"
    fi
    if should_process "a2a_exponential_skewed_${LOW_TEMP_SUFFIX}"; then
      run_gen python3 connection_matrices/gen_serial_alltoall.py "$A2A_EXPONENTIAL_SKEWED_LOW_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$LOW_FLOWSIZE_A2A" "$LOW_EXTRA_START_US_A2A" "$SEED" "$EXPONENTIAL_SKEWED_SPEC"
    fi
  else
    if should_process "a2a_bimodal_${LOW_TEMP_SUFFIX}"; then
      run_gen python3 connection_matrices/gen_serialn_alltoall.py "$A2A_BIMODAL_LOW_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$LOW_A2A_PARALLEL" "$LOW_FLOWSIZE_A2A" "$LOW_EXTRA_START_US_A2A" "$SEED" "$BIMODAL_SPEC"
    fi
    if should_process "a2a_pareto_${LOW_TEMP_SUFFIX}"; then
      run_gen python3 connection_matrices/gen_serialn_alltoall.py "$A2A_PARETO_LOW_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$LOW_A2A_PARALLEL" "$LOW_FLOWSIZE_A2A" "$LOW_EXTRA_START_US_A2A" "$SEED" "$LOW_PARETO_SPEC"
    fi
    if should_process "a2a_pareto_heavy_${LOW_TEMP_SUFFIX}"; then
      run_gen python3 connection_matrices/gen_serialn_alltoall.py "$A2A_PARETO_HEAVY_LOW_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$LOW_A2A_PARALLEL" "$LOW_FLOWSIZE_A2A" "$LOW_EXTRA_START_US_A2A" "$SEED" "$LOW_PARETO_HEAVY_SPEC"
    fi
    if should_process "a2a_lognormal_skewed_${LOW_TEMP_SUFFIX}"; then
      run_gen python3 connection_matrices/gen_serialn_alltoall.py "$A2A_LOGNORMAL_SKEWED_LOW_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$LOW_A2A_PARALLEL" "$LOW_FLOWSIZE_A2A" "$LOW_EXTRA_START_US_A2A" "$SEED" "$LOGNORMAL_SKEWED_SPEC"
    fi
    if should_process "a2a_exponential_skewed_${LOW_TEMP_SUFFIX}"; then
      run_gen python3 connection_matrices/gen_serialn_alltoall.py "$A2A_EXPONENTIAL_SKEWED_LOW_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$LOW_A2A_PARALLEL" "$LOW_FLOWSIZE_A2A" "$LOW_EXTRA_START_US_A2A" "$SEED" "$EXPONENTIAL_SKEWED_SPEC"
    fi
  fi

  run_ndp "incast_mono_${LOW_TEMP_SUFFIX}" "$INC_LOW_CM" "$CONNS_INCAST" "$LOW_END_US_INCAST"
  run_ndp "a2a_mono_${LOW_TEMP_SUFFIX}" "$A2A_LOW_CM" "$A2A_CONNS" "$LOW_END_US_A2A"
  run_ndp "incast_bimodal_${LOW_TEMP_SUFFIX}" "$INCAST_BIMODAL_LOW_CM" "$CONNS_INCAST" "$LOW_END_US_INCAST"
  run_ndp "a2a_bimodal_${LOW_TEMP_SUFFIX}" "$A2A_BIMODAL_LOW_CM" "$A2A_CONNS" "$LOW_END_US_A2A"
  run_ndp "incast_pareto_${LOW_TEMP_SUFFIX}" "$INCAST_PARETO_LOW_CM" "$CONNS_INCAST" "$LOW_END_US_INCAST"
  run_ndp "a2a_pareto_${LOW_TEMP_SUFFIX}" "$A2A_PARETO_LOW_CM" "$A2A_CONNS" "$LOW_END_US_A2A"
  run_ndp "incast_pareto_heavy_${LOW_TEMP_SUFFIX}" "$INCAST_PARETO_HEAVY_LOW_CM" "$CONNS_INCAST" "$LOW_END_US_INCAST"
  run_ndp "a2a_pareto_heavy_${LOW_TEMP_SUFFIX}" "$A2A_PARETO_HEAVY_LOW_CM" "$A2A_CONNS" "$LOW_END_US_A2A"
  run_ndp "incast_lognormal_skewed_${LOW_TEMP_SUFFIX}" "$INCAST_LOGNORMAL_SKEWED_LOW_CM" "$CONNS_INCAST" "$LOW_END_US_INCAST"
  run_ndp "a2a_lognormal_skewed_${LOW_TEMP_SUFFIX}" "$A2A_LOGNORMAL_SKEWED_LOW_CM" "$A2A_CONNS" "$LOW_END_US_A2A"
  run_ndp "incast_exponential_skewed_${LOW_TEMP_SUFFIX}" "$INCAST_EXPONENTIAL_SKEWED_LOW_CM" "$CONNS_INCAST" "$LOW_END_US_INCAST"
  run_ndp "a2a_exponential_skewed_${LOW_TEMP_SUFFIX}" "$A2A_EXPONENTIAL_SKEWED_LOW_CM" "$A2A_CONNS" "$LOW_END_US_A2A"
fi

echo
echo "Done. total_written_lines=$TOTAL_WRITTEN_LINES"
