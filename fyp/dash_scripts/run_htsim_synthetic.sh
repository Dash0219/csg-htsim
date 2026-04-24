#!/usr/bin/env bash
set -euo pipefail

print_usage() {
  cat <<'EOF'
Usage:
  bash fyp/dash_scripts/run_htsim_synthetic.sh [options]

Options:
  -d, --dataset NAME        Run one dataset name/pattern (example: a2a_pareto)
  -p, --protocol NAME       Transport protocol: ndp or hpcc (default: ndp)
  --flow-size-sweep      Enable mono flow-size sweep datasets
  --no-flow-size-sweep   Disable mono flow-size sweep datasets
  --flow-size-values L   Comma-separated packet counts for sweep datasets
  --temporal-sweep       Enable temporal-locality sweep datasets
  --no-temporal-sweep    Disable temporal-locality sweep datasets
  --temporal-values L    Comma-separated temporal spread multipliers (default: 1,2,4,8)
  -s, --seed N              Random seed for matrix generators (default: current epoch seconds)
  -h, --help           Show this help

Accepted dataset names/patterns for --dataset:
  Base datasets:
    incast_mono | a2a_mono | incast_bimodal | a2a_bimodal
    incast_pareto | a2a_pareto | incast_heavytail | a2a_heavytail
    incast_exponential_skewed | a2a_exponential_skewed
  Sweep datasets:
    (incast|a2a)_mono_<N>
    (incast|a2a)_mono_burst_<N>
    (incast|a2a)_pareto_alpha_<A>        (A tokenized, e.g. 1p0, 1p5)
    (incast|a2a)_heavytail_temp_<N>
    (incast|a2a)_heavytail_sigma_<S>     (S tokenized, e.g. 1p0, 1p5, 2p0)
  Sweep shorthand:
    a2a_mono_n / incast_mono_n                   (all mono_<N> flow-size sweep datasets for one topology)
    a2a_mono_burst_n / incast_mono_burst_n       (all mono_burst_<N> sweep datasets for one topology)
    a2a_pareto_alpha_n / incast_pareto_alpha_n   (all pareto_alpha_<A> sweep datasets for one topology)
    a2a_heavytail_temp_n / incast_heavytail_temp_n (all heavytail_temp_<N> temporal-locality sweep datasets)
    a2a_heavytail_sigma_n / incast_heavytail_sigma_n (all heavytail_sigma_<S> sweep datasets for one topology)

Environment variables:
  PROTOCOL             Equivalent to --protocol (ndp/hpcc)
  ROUTE_PATHS          Path entropy count passed as -paths (default: 8)
  ROUTE_PATH_BURST     NDP-only burst passed as -path_burst (default: 64)
  NDP_PATHS            Legacy alias for ROUTE_PATHS
  NDP_PATH_BURST       Legacy alias for ROUTE_PATH_BURST
  GENERATE_FLOW_SIZE_SWEEP  Enable/disable mono flow-size sweep datasets (1/0)
  FLOW_SIZE_SWEEP_VALUES    Comma-separated sweep packet counts, must be 1,2,4,...
  FLOW_SWEEP_PKT_BYTES      Bytes per packet for sweep conversion (default: 9000)
  FLOW_SWEEP_CONNS_INCAST   Incast source count for mono flow-size sweep (default: 128)
  FLOW_SWEEP_A2A_CONNS      A2A source count for mono flow-size sweep (default: 256)
  FLOW_SWEEP_A2A_GROUPSIZE  A2A group size for mono flow-size sweep (default: 64)
  FLOW_SWEEP_A2A_PARALLEL   A2A per-source parallel conns for mono sweep (default: 1)
  FLOW_SWEEP_END_US_INCAST  Optional absolute incast sim end time (us) for mono sweep
  FLOW_SWEEP_END_US_A2A     Optional absolute A2A sim end time (us) for mono sweep
  FLOW_SWEEP_END_US_INCAST_BASE  Base incast end time (us) multiplied by packet count when absolute end is unset (default: 20000)
  FLOW_SWEEP_END_US_A2A_BASE     Base A2A end time (us) multiplied by packet count when absolute end is unset (default: 20000)
  GENERATE_BURST_SWEEP  Enable/disable mono burstiness sweep datasets (1/0)
  BURST_SWEEP_VALUES    Comma-separated ROUTE_PATH_BURST values for burst sweep (default: 8,16,32,64,128,256)
  BURST_MONO_PACKETS    Fixed mono packet count used by burst sweep datasets (default: 1024)
  BURST_BASE_EXTRA_START_US      Non-NDP fallback base start spread (us) scaled as 1/value for incast burst sweep
  BURST_BASE_EXTRA_START_US_A2A  Non-NDP fallback base start spread (us) scaled as 1/value for A2A burst sweep
  GENERATE_PARETO_SKEW_SWEEP     Enable/disable Pareto alpha skew sweep datasets (1/0)
  PARETO_ALPHA_SWEEP_VALUES      Comma-separated Pareto alpha values for skew sweep (default: 1.0,1.5,2.0,2.5,3.0,3.5)
  PARETO_SKEW_BASE_XM            Constant Pareto minimum value x_m used for alpha sweep (default: 1)
  PARETO_SKEW_MAX_SIZE           Pareto max flow size for alpha sweep (default: 20000000)
  SKEW_TARGET_TOTAL_BYTES_INCAST Optional target total bytes for incast alpha sweep normalization
  SKEW_TARGET_TOTAL_BYTES_A2A    Optional target total bytes for A2A alpha sweep normalization
  GENERATE_HEAVYTAIL_SIGMA_SWEEP Enable/disable heavytail sigma concentration sweep datasets (1/0)
  HEAVYTAIL_SIGMA_SWEEP_VALUES   Comma-separated sigma values (default: 0.5,1.0,1.5,2.0,2.5,3.0)
  HEAVYTAIL_MIN_SIZE             Heavytail minimum/median flow size in bytes (default: 9000, ~1 packet)
  HEAVYTAIL_MAX_SIZE             Heavytail maximum flow size in bytes (default: 50000000)
  HEAVYTAIL_SPEC                 Base heavytail spec used for incast_heavytail/a2a_heavytail (default: heavytail:2.0:<min>:<max>)
  GENERATE_TEMPORAL_SWEEP   Enable/disable temporal-locality sweep datasets (1/0)
  TEMPORAL_SWEEP_VALUES     Comma-separated temporal spread multipliers (default: 1,2,4,8)
  HEAVYTAIL_TEMP_SIGMA           Concentration sigma for heavytail_temp distribution (default: 2.0)
  HEAVYTAIL_TEMP_MIN_SIZE        Base median flow size in bytes for heavytail_temp (scaled by multiplier, default: HEAVYTAIL_MIN_SIZE)
  HEAVYTAIL_TEMP_MAX_SIZE        Max flow size for heavytail_temp (default: HEAVYTAIL_MAX_SIZE)
  TEMPORAL_BASE_EXTRA_START_US      Base incast extra start spread (us) multiplied by temporal multiplier (default: 200)
  TEMPORAL_BASE_EXTRA_START_US_A2A  Base A2A extra start spread (us) multiplied by temporal multiplier (default: 200)
  FLOW_SWEEP_NORMALIZE_PKTS  Normalize total packets across mono_N sweep (1=yes, 0=no, default: 1)
  FLOW_SWEEP_BASE_PKTS       Reference packet count for normalization; conns scales as BASE_PKTS/N (default: 256)
  FLOW_SWEEP_MIN_CONNS_INCAST  Minimum incast conns when normalized (default: 4)
  SEED                 Equivalent to --seed
  DATASET              Equivalent to --dataset
  TARGET_PATTERN       Deprecated legacy alias for DATASET
EOF
}

DATASET="${DATASET:-}"
TARGET_PATTERN="${TARGET_PATTERN:-}"
DATASET_FAMILY_PREFIX=""
DATASET_FAMILY_KIND=""
PROTOCOL="${PROTOCOL:-ndp}"
SEED="${SEED:-}"
GENERATE_FLOW_SIZE_SWEEP="${GENERATE_FLOW_SIZE_SWEEP:-}"
FLOW_SIZE_SWEEP_VALUES="${FLOW_SIZE_SWEEP_VALUES:-1,2,4,8,16,32,64,128,256,512,1024,2048,4096}"
GENERATE_BURST_SWEEP="${GENERATE_BURST_SWEEP:-}"
BURST_SWEEP_VALUES="${BURST_SWEEP_VALUES:-8,16,32,64,128,256}"
BURST_MONO_PACKETS="${BURST_MONO_PACKETS:-1024}"
GENERATE_PARETO_SKEW_SWEEP="${GENERATE_PARETO_SKEW_SWEEP:-1}"
PARETO_ALPHA_SWEEP_VALUES="${PARETO_ALPHA_SWEEP_VALUES-1.0,1.5,2.0,2.5,3.0,3.5}"
PARETO_SKEW_BASE_XM="${PARETO_SKEW_BASE_XM:-1}"
PARETO_SKEW_MAX_SIZE="${PARETO_SKEW_MAX_SIZE:-20000000}"
SKEW_TARGET_TOTAL_BYTES_INCAST="${SKEW_TARGET_TOTAL_BYTES_INCAST:-0}"
SKEW_TARGET_TOTAL_BYTES_A2A="${SKEW_TARGET_TOTAL_BYTES_A2A:-0}"
GENERATE_HEAVYTAIL_SIGMA_SWEEP="${GENERATE_HEAVYTAIL_SIGMA_SWEEP:-1}"
HEAVYTAIL_SIGMA_SWEEP_VALUES="${HEAVYTAIL_SIGMA_SWEEP_VALUES:-0.5,1.0,1.5,2.0,2.5,3.0}"
HEAVYTAIL_MIN_SIZE="${HEAVYTAIL_MIN_SIZE:-9000}"
HEAVYTAIL_MAX_SIZE="${HEAVYTAIL_MAX_SIZE:-50000000}"
GENERATE_TEMPORAL_SWEEP="${GENERATE_TEMPORAL_SWEEP:-1}"
TEMPORAL_SWEEP_VALUES="${TEMPORAL_SWEEP_VALUES:-1,2,4,8}"
HEAVYTAIL_TEMP_SIGMA="${HEAVYTAIL_TEMP_SIGMA:-2.0}"
HEAVYTAIL_TEMP_MIN_SIZE="${HEAVYTAIL_TEMP_MIN_SIZE:-${HEAVYTAIL_MIN_SIZE}}"
HEAVYTAIL_TEMP_MAX_SIZE="${HEAVYTAIL_TEMP_MAX_SIZE:-${HEAVYTAIL_MAX_SIZE}}"
FLOW_SWEEP_NORMALIZE_PKTS="${FLOW_SWEEP_NORMALIZE_PKTS:-1}"
FLOW_SWEEP_BASE_PKTS="${FLOW_SWEEP_BASE_PKTS:-256}"
FLOW_SWEEP_MIN_CONNS_INCAST="${FLOW_SWEEP_MIN_CONNS_INCAST:-4}"

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
    --temporal-sweep)
      GENERATE_TEMPORAL_SWEEP=1
      shift
      ;;
    --no-temporal-sweep)
      GENERATE_TEMPORAL_SWEEP=0
      shift
      ;;
    --temporal-values)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --temporal-values requires a value" >&2
        exit 1
      fi
      TEMPORAL_SWEEP_VALUES="$2"
      shift 2
      ;;
    --flow-size-sweep)
      GENERATE_FLOW_SIZE_SWEEP=1
      shift
      ;;
    --no-flow-size-sweep)
      GENERATE_FLOW_SIZE_SWEEP=0
      shift
      ;;
    --flow-size-values)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --flow-size-values requires a value" >&2
        exit 1
      fi
      FLOW_SIZE_SWEEP_VALUES="$2"
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

# Generate synthetic INT logs using HTSIM transport runs.
# Dataset logs below are stderr-only (INT traces).
# Stdout progress/debug output is written to fyp/dash_results/synthetic/<protocol>/raw_logs/*.raw.log.
# Output files are written to:
#   fyp/dash_dataset/synthetic/<protocol>/log_incast_mono.txt
#   fyp/dash_dataset/synthetic/<protocol>/log_a2a_mono.txt
#   fyp/dash_dataset/synthetic/<protocol>/log_incast_bimodal.txt
#   fyp/dash_dataset/synthetic/<protocol>/log_a2a_bimodal.txt
#   fyp/dash_dataset/synthetic/<protocol>/log_incast_pareto.txt
#   fyp/dash_dataset/synthetic/<protocol>/log_a2a_pareto.txt
#   fyp/dash_dataset/synthetic/<protocol>/log_incast_exponential_skewed.txt
#   fyp/dash_dataset/synthetic/<protocol>/log_a2a_exponential_skewed.txt
# Optional temporal-locality variants:
#   fyp/dash_dataset/synthetic/<protocol>/log_<pattern>_temp_<multiplier>.txt

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

if [[ "$PROTOCOL" != "ndp" && "$PROTOCOL" != "hpcc" ]]; then
  echo "ERROR: --protocol must be ndp or hpcc" >&2
  exit 1
fi

SIM_BIN="./sim/datacenter/htsim_${PROTOCOL}"
if [[ ! -x "$SIM_BIN" ]]; then
  echo "ERROR: $SIM_BIN not found or not executable. Build first with: make -C sim/datacenter all"
  exit 1
fi

OUT_DIR="fyp/dash_dataset/synthetic/${PROTOCOL}"
CM_DIR="fyp/dash_results/synthetic/${PROTOCOL}/connection_matrices"
RUN_DIR="fyp/dash_results/synthetic/${PROTOCOL}/raw_logs"

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
if [[ -n "${ROUTE_STRAT:-}" ]]; then
  ROUTE_STRAT="$ROUTE_STRAT"
elif [[ "$PROTOCOL" == "hpcc" ]]; then
  # main_hpcc only supports single-path or ECMP-FIB modes.
  ROUTE_STRAT="ecmp_host"
else
  ROUTE_STRAT="perm"
fi
NDP_PATHS="${NDP_PATHS:-8}"
NDP_PATH_BURST="${NDP_PATH_BURST:-64}"
ROUTE_PATHS="${ROUTE_PATHS:-$NDP_PATHS}"
ROUTE_PATH_BURST="${ROUTE_PATH_BURST:-$NDP_PATH_BURST}"

A2A_CONNS="${A2A_CONNS:-512}"
A2A_GROUPSIZE="${A2A_GROUPSIZE:-512}"
A2A_PARALLEL="${A2A_PARALLEL:-64}"
FLOWSIZE_A2A="${FLOWSIZE_A2A:-1000000}"
EXTRA_START_US_A2A="${EXTRA_START_US_A2A:-0}"

BIMODAL_SPEC="${BIMODAL_SPEC:-bimodal:0.9:1:10000000}"
PARETO_SPEC="${PARETO_SPEC:-pareto:800:1.1:20000000}"

# Additional skewed distribution used in proof-of-concept set
EXPONENTIAL_SKEWED_SPEC="${EXPONENTIAL_SKEWED_SPEC:-exponential:200000:50000000}"

TEMPORAL_BASE_EXTRA_START_US="${TEMPORAL_BASE_EXTRA_START_US:-200}"
TEMPORAL_BASE_EXTRA_START_US_A2A="${TEMPORAL_BASE_EXTRA_START_US_A2A:-200}"
TEMPORAL_END_MARGIN_US="${TEMPORAL_END_MARGIN_US:-200}"
BURST_BASE_EXTRA_START_US="${BURST_BASE_EXTRA_START_US:-2048}"
BURST_BASE_EXTRA_START_US_A2A="${BURST_BASE_EXTRA_START_US_A2A:-2048}"

# Dedicated knobs for the mono flow-size sweep to keep concurrency controlled
# and avoid very long generation/simulation runs.
FLOW_SWEEP_CONNS_INCAST="${FLOW_SWEEP_CONNS_INCAST:-128}"
FLOW_SWEEP_A2A_CONNS="${FLOW_SWEEP_A2A_CONNS:-256}"
FLOW_SWEEP_A2A_GROUPSIZE="${FLOW_SWEEP_A2A_GROUPSIZE:-64}"
FLOW_SWEEP_A2A_PARALLEL="${FLOW_SWEEP_A2A_PARALLEL:-1}"
FLOW_SWEEP_EXTRA_START_US="${FLOW_SWEEP_EXTRA_START_US:-$EXTRA_START_US}"
FLOW_SWEEP_EXTRA_START_US_A2A="${FLOW_SWEEP_EXTRA_START_US_A2A:-$EXTRA_START_US_A2A}"
FLOW_SWEEP_END_US_INCAST="${FLOW_SWEEP_END_US_INCAST:-}"
FLOW_SWEEP_END_US_A2A="${FLOW_SWEEP_END_US_A2A:-}"
FLOW_SWEEP_END_US_INCAST_BASE="${FLOW_SWEEP_END_US_INCAST_BASE:-20000}"
FLOW_SWEEP_END_US_A2A_BASE="${FLOW_SWEEP_END_US_A2A_BASE:-20000}"
FLOW_SWEEP_PKT_BYTES="${FLOW_SWEEP_PKT_BYTES:-9000}"

if [[ -z "$GENERATE_FLOW_SIZE_SWEEP" ]]; then
  GENERATE_FLOW_SIZE_SWEEP=1
fi

if [[ "$GENERATE_FLOW_SIZE_SWEEP" != "0" && "$GENERATE_FLOW_SIZE_SWEEP" != "1" ]]; then
  echo "ERROR: GENERATE_FLOW_SIZE_SWEEP must be 0 or 1" >&2
  exit 1
fi

if [[ -z "$GENERATE_BURST_SWEEP" ]]; then
  GENERATE_BURST_SWEEP=1
fi

if [[ "$GENERATE_BURST_SWEEP" != "0" && "$GENERATE_BURST_SWEEP" != "1" ]]; then
  echo "ERROR: GENERATE_BURST_SWEEP must be 0 or 1" >&2
  exit 1
fi

if [[ "$GENERATE_PARETO_SKEW_SWEEP" != "0" && "$GENERATE_PARETO_SKEW_SWEEP" != "1" ]]; then
  echo "ERROR: GENERATE_PARETO_SKEW_SWEEP must be 0 or 1" >&2
  exit 1
fi

if [[ "$GENERATE_HEAVYTAIL_SIGMA_SWEEP" != "0" && "$GENERATE_HEAVYTAIL_SIGMA_SWEEP" != "1" ]]; then
  echo "ERROR: GENERATE_HEAVYTAIL_SIGMA_SWEEP must be 0 or 1" >&2
  exit 1
fi

if [[ "$GENERATE_TEMPORAL_SWEEP" != "0" && "$GENERATE_TEMPORAL_SWEEP" != "1" ]]; then
  echo "ERROR: GENERATE_TEMPORAL_SWEEP must be 0 or 1" >&2
  exit 1
fi

PARETO_ALPHA_SWEEP_LIST=()
_raw_alphas=()
if [[ -n "$PARETO_ALPHA_SWEEP_VALUES" ]]; then
  IFS=',' read -r -a _raw_alphas <<< "$PARETO_ALPHA_SWEEP_VALUES"
fi
for raw in "${_raw_alphas[@]:-}"; do
  alpha="${raw//[[:space:]]/}"
  [[ -n "$alpha" ]] || continue
  if ! [[ "$alpha" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    echo "ERROR: invalid alpha value '$alpha' in PARETO_ALPHA_SWEEP_VALUES" >&2
    exit 1
  fi
  PARETO_ALPHA_SWEEP_LIST+=("$alpha")
done

if [[ -n "$DATASET" && "$DATASET" =~ ^(incast|a2a)_pareto_alpha_([0-9]+(p[0-9]+)?)$ ]]; then
  _tok="${BASH_REMATCH[2]}"
  _alpha="${_tok/p/.}"
  found=0
  for a in "${PARETO_ALPHA_SWEEP_LIST[@]:-}"; do
    [[ "$a" == "$_alpha" ]] && found=1 && break
  done
  if [[ "$found" == "0" ]]; then
    PARETO_ALPHA_SWEEP_LIST+=("$_alpha")
  fi
fi

_pareto_alpha_count=0
for _a in "${PARETO_ALPHA_SWEEP_LIST[@]:-}"; do
  [[ -n "$_a" ]] && _pareto_alpha_count=$((_pareto_alpha_count + 1))
done
if [[ "$GENERATE_PARETO_SKEW_SWEEP" == "1" && $_pareto_alpha_count -eq 0 ]]; then
  echo "ERROR: Pareto skew sweep enabled but no alpha values were provided" >&2
  exit 1
fi

HEAVYTAIL_SIGMA_SWEEP_LIST=()
_raw_sigmas=()
if [[ -n "$HEAVYTAIL_SIGMA_SWEEP_VALUES" ]]; then
  IFS=',' read -r -a _raw_sigmas <<< "$HEAVYTAIL_SIGMA_SWEEP_VALUES"
fi
for raw in "${_raw_sigmas[@]:-}"; do
  sigma="${raw//[[:space:]]/}"
  [[ -n "$sigma" ]] || continue
  if ! [[ "$sigma" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    echo "ERROR: invalid sigma value '$sigma' in HEAVYTAIL_SIGMA_SWEEP_VALUES" >&2
    exit 1
  fi
  HEAVYTAIL_SIGMA_SWEEP_LIST+=("$sigma")
done

if [[ -n "$DATASET" && "$DATASET" =~ ^(incast|a2a)_heavytail_sigma_([0-9]+(p[0-9]+)?)$ ]]; then
  _tok="${BASH_REMATCH[2]}"
  _sigma="${_tok/p/.}"
  found=0
  for s in "${HEAVYTAIL_SIGMA_SWEEP_LIST[@]:-}"; do
    [[ "$s" == "$_sigma" ]] && found=1 && break
  done
  if [[ "$found" == "0" ]]; then
    HEAVYTAIL_SIGMA_SWEEP_LIST+=("$_sigma")
  fi
fi

_heavytail_sigma_count=0
for _s in "${HEAVYTAIL_SIGMA_SWEEP_LIST[@]:-}"; do
  [[ -n "$_s" ]] && _heavytail_sigma_count=$((_heavytail_sigma_count + 1))
done
if [[ "$GENERATE_HEAVYTAIL_SIGMA_SWEEP" == "1" && $_heavytail_sigma_count -eq 0 ]]; then
  echo "ERROR: Heavytail sigma sweep enabled but no sigma values were provided" >&2
  exit 1
fi

TEMPORAL_SWEEP_LIST=()
IFS=',' read -r -a _raw_temporal <<< "$TEMPORAL_SWEEP_VALUES"
for raw in "${_raw_temporal[@]}"; do
  mult="${raw//[[:space:]]/}"
  [[ -n "$mult" ]] || continue
  if ! [[ "$mult" =~ ^[0-9]+$ ]]; then
    echo "ERROR: invalid temporal multiplier '$mult' in TEMPORAL_SWEEP_VALUES" >&2
    exit 1
  fi
  if (( mult <= 0 )); then
    echo "ERROR: temporal multipliers must be > 0" >&2
    exit 1
  fi
  TEMPORAL_SWEEP_LIST+=("$mult")
done

if [[ "$GENERATE_TEMPORAL_SWEEP" == "1" && ${#TEMPORAL_SWEEP_LIST[@]} -eq 0 ]]; then
  echo "ERROR: temporal sweep enabled but no valid TEMPORAL_SWEEP_VALUES were provided" >&2
  exit 1
fi

BURST_SWEEP_LIST=()
IFS=',' read -r -a _raw_bursts <<< "$BURST_SWEEP_VALUES"
for raw in "${_raw_bursts[@]}"; do
  burst="${raw//[[:space:]]/}"
  [[ -n "$burst" ]] || continue
  if ! [[ "$burst" =~ ^[0-9]+$ ]]; then
    echo "ERROR: invalid burst value '$burst' in BURST_SWEEP_VALUES" >&2
    exit 1
  fi
  if (( burst <= 0 )); then
    echo "ERROR: burst values must be > 0" >&2
    exit 1
  fi
  BURST_SWEEP_LIST+=("$burst")
done

if [[ "$GENERATE_BURST_SWEEP" == "1" && ${#BURST_SWEEP_LIST[@]} -eq 0 ]]; then
  echo "ERROR: burst sweep enabled but no valid BURST_SWEEP_VALUES were provided" >&2
  exit 1
fi

FLOW_SIZE_SWEEP_LIST=()
IFS=',' read -r -a _raw_sizes <<< "$FLOW_SIZE_SWEEP_VALUES"
for raw in "${_raw_sizes[@]}"; do
  size="${raw//[[:space:]]/}"
  [[ -n "$size" ]] || continue
  if ! [[ "$size" =~ ^[0-9]+$ ]]; then
    echo "ERROR: invalid flow-size value '$size' in FLOW_SIZE_SWEEP_VALUES" >&2
    exit 1
  fi
  if (( size <= 0 )); then
    echo "ERROR: flow-size values must be > 0" >&2
    exit 1
  fi
  FLOW_SIZE_SWEEP_LIST+=("$size")
done

if [[ "$GENERATE_FLOW_SIZE_SWEEP" == "1" && ${#FLOW_SIZE_SWEEP_LIST[@]} -eq 0 ]]; then
  echo "ERROR: flow-size sweep enabled but no valid FLOW_SIZE_SWEEP_VALUES were provided" >&2
  exit 1
fi

if [[ "$GENERATE_FLOW_SIZE_SWEEP" == "1" ]]; then
  if [[ "${FLOW_SIZE_SWEEP_LIST[0]}" != "1" ]]; then
    echo "ERROR: FLOW_SIZE_SWEEP_VALUES must start at 1" >&2
    exit 1
  fi
  prev=1
  for ((idx=1; idx<${#FLOW_SIZE_SWEEP_LIST[@]}; idx++)); do
    cur="${FLOW_SIZE_SWEEP_LIST[$idx]}"
    if (( cur != prev * 2 )); then
      echo "ERROR: FLOW_SIZE_SWEEP_VALUES must be powers-of-two with exponential steps (.., ${prev}, $((prev*2)), ..)" >&2
      exit 1
    fi
    prev="$cur"
  done
fi

if (( FLOW_SWEEP_CONNS_INCAST <= 0 )); then
  echo "ERROR: FLOW_SWEEP_CONNS_INCAST must be > 0" >&2
  exit 1
fi
if (( FLOW_SWEEP_A2A_GROUPSIZE <= 1 )); then
  echo "ERROR: FLOW_SWEEP_A2A_GROUPSIZE must be > 1" >&2
  exit 1
fi
if (( FLOW_SWEEP_A2A_CONNS <= 0 || FLOW_SWEEP_A2A_CONNS % FLOW_SWEEP_A2A_GROUPSIZE != 0 )); then
  echo "ERROR: FLOW_SWEEP_A2A_CONNS must be > 0 and a multiple of FLOW_SWEEP_A2A_GROUPSIZE" >&2
  exit 1
fi
if (( FLOW_SWEEP_A2A_PARALLEL <= 0 || FLOW_SWEEP_A2A_PARALLEL > FLOW_SWEEP_A2A_GROUPSIZE - 1 )); then
  echo "ERROR: FLOW_SWEEP_A2A_PARALLEL must be in [1, FLOW_SWEEP_A2A_GROUPSIZE-1]" >&2
  exit 1
fi
if [[ -n "$FLOW_SWEEP_END_US_INCAST" ]] && ! [[ "$FLOW_SWEEP_END_US_INCAST" =~ ^[0-9]+$ ]]; then
  echo "ERROR: FLOW_SWEEP_END_US_INCAST must be a positive integer when set" >&2
  exit 1
fi
if [[ -n "$FLOW_SWEEP_END_US_A2A" ]] && ! [[ "$FLOW_SWEEP_END_US_A2A" =~ ^[0-9]+$ ]]; then
  echo "ERROR: FLOW_SWEEP_END_US_A2A must be a positive integer when set" >&2
  exit 1
fi
if (( FLOW_SWEEP_END_US_INCAST_BASE <= 0 )); then
  echo "ERROR: FLOW_SWEEP_END_US_INCAST_BASE must be > 0" >&2
  exit 1
fi
if (( FLOW_SWEEP_END_US_A2A_BASE <= 0 )); then
  echo "ERROR: FLOW_SWEEP_END_US_A2A_BASE must be > 0" >&2
  exit 1
fi
if (( FLOW_SWEEP_PKT_BYTES <= 0 )); then
  echo "ERROR: FLOW_SWEEP_PKT_BYTES must be > 0" >&2
  exit 1
fi
if ! [[ "$BURST_MONO_PACKETS" =~ ^[0-9]+$ ]] || (( BURST_MONO_PACKETS <= 0 )); then
  echo "ERROR: BURST_MONO_PACKETS must be a positive integer" >&2
  exit 1
fi

if [[ "$PROTOCOL" == "hpcc" ]]; then
  case "$ROUTE_STRAT" in
    single|ecmp_host|ecmp_ar|ecmp_host_ar|ecmp_rr)
      ;;
    *)
      echo "ERROR: ROUTE_STRAT=$ROUTE_STRAT is unsupported for hpcc." >&2
      echo "Use one of: single, ecmp_host, ecmp_ar, ecmp_host_ar, ecmp_rr" >&2
      exit 1
      ;;
  esac
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
    *)
      echo "$name"
      ;;
  esac
}

if [[ -n "$DATASET" ]]; then
  DATASET="$(normalize_dataset_alias "$DATASET")"
fi

if [[ -n "$DATASET" && "$DATASET" =~ ^(incast|a2a)_mono_n$ ]]; then
  DATASET_FAMILY_PREFIX="${BASH_REMATCH[1]}_mono_"
  DATASET_FAMILY_KIND="mono"
  DATASET=""
  GENERATE_FLOW_SIZE_SWEEP=1
  GENERATE_BURST_SWEEP=0
  GENERATE_PARETO_SKEW_SWEEP=0
  GENERATE_HEAVYTAIL_SIGMA_SWEEP=0
  GENERATE_TEMPORAL_SWEEP=0
elif [[ -n "$DATASET" && "$DATASET" =~ ^(incast|a2a)_mono_burst_n$ ]]; then
  DATASET_FAMILY_PREFIX="${BASH_REMATCH[1]}_mono_burst_"
  DATASET_FAMILY_KIND="mono_burst"
  DATASET=""
  GENERATE_FLOW_SIZE_SWEEP=0
  GENERATE_BURST_SWEEP=1
  GENERATE_PARETO_SKEW_SWEEP=0
  GENERATE_HEAVYTAIL_SIGMA_SWEEP=0
  GENERATE_TEMPORAL_SWEEP=0
elif [[ -n "$DATASET" && "$DATASET" =~ ^(incast|a2a)_pareto_alpha_n$ ]]; then
  DATASET_FAMILY_PREFIX="${BASH_REMATCH[1]}_pareto_alpha_"
  DATASET_FAMILY_KIND="pareto_alpha"
  DATASET=""
  GENERATE_FLOW_SIZE_SWEEP=0
  GENERATE_BURST_SWEEP=0
  GENERATE_PARETO_SKEW_SWEEP=1
  GENERATE_HEAVYTAIL_SIGMA_SWEEP=0
  GENERATE_TEMPORAL_SWEEP=0
elif [[ -n "$DATASET" && "$DATASET" =~ ^(incast|a2a)_heavytail_temp_n$ ]]; then
  DATASET_FAMILY_PREFIX="${BASH_REMATCH[1]}_heavytail_temp_"
  DATASET_FAMILY_KIND="heavytail_temp"
  DATASET=""
  GENERATE_FLOW_SIZE_SWEEP=0
  GENERATE_BURST_SWEEP=0
  GENERATE_PARETO_SKEW_SWEEP=0
  GENERATE_HEAVYTAIL_SIGMA_SWEEP=0
  GENERATE_TEMPORAL_SWEEP=1
elif [[ -n "$DATASET" && "$DATASET" =~ ^(incast|a2a)_heavytail_sigma_n$ ]]; then
  DATASET_FAMILY_PREFIX="${BASH_REMATCH[1]}_heavytail_sigma_"
  DATASET_FAMILY_KIND="heavytail_sigma"
  DATASET=""
  GENERATE_FLOW_SIZE_SWEEP=0
  GENERATE_BURST_SWEEP=0
  GENERATE_PARETO_SKEW_SWEEP=0
  GENERATE_HEAVYTAIL_SIGMA_SWEEP=1
  GENERATE_TEMPORAL_SWEEP=0
fi

is_flow_size_sweep_dataset() {
  local name="$1"
  [[ "$name" =~ ^(incast|a2a)_mono_[0-9]+$ ]]
}

is_burst_sweep_dataset() {
  local name="$1"
  [[ "$name" =~ ^(incast|a2a)_mono_burst_[0-9]+$ ]]
}

is_temporal_sweep_dataset() {
  local name="$1"
  [[ "$name" =~ ^(incast|a2a)_heavytail_temp_[0-9]+$ ]]
}

is_pareto_alpha_sweep_dataset() {
  local name="$1"
  [[ "$name" =~ ^(incast|a2a)_pareto_alpha_[0-9]+(p[0-9]+)?$ ]]
}

is_heavytail_sigma_sweep_dataset() {
  local name="$1"
  [[ "$name" =~ ^(incast|a2a)_heavytail_sigma_[0-9]+(p[0-9]+)?$ ]]
}

is_valid_dataset() {
  local name="$1"
  if [[ "$name" =~ ^(incast|a2a)_(mono|mono_burst|pareto_alpha|heavytail_temp|heavytail_sigma)_n$ ]]; then
    return 0
  fi
  if is_flow_size_sweep_dataset "$name"; then
    return 0
  fi
  if is_burst_sweep_dataset "$name"; then
    return 0
  fi
  if is_temporal_sweep_dataset "$name"; then
    return 0
  fi
  if is_pareto_alpha_sweep_dataset "$name"; then
    return 0
  fi
  if is_heavytail_sigma_sweep_dataset "$name"; then
    return 0
  fi
  case "$name" in
    incast_mono|a2a_mono|incast_bimodal|a2a_bimodal|incast_pareto|a2a_pareto|incast_heavytail|a2a_heavytail|incast_exponential_skewed|a2a_exponential_skewed)
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
INCAST_HEAVYTAIL_CM="$CM_DIR/incast_heavytail.cm"
A2A_HEAVYTAIL_CM="$CM_DIR/a2a_heavytail.cm"
INCAST_EXPONENTIAL_SKEWED_CM="$CM_DIR/incast_exponential_skewed.cm"
A2A_EXPONENTIAL_SKEWED_CM="$CM_DIR/a2a_exponential_skewed.cm"

# Default heavytail spec: sigma=2.0, median=HEAVYTAIL_MIN_SIZE, max=HEAVYTAIL_MAX_SIZE
HEAVYTAIL_SPEC="${HEAVYTAIL_SPEC:-heavytail:2.0:${HEAVYTAIL_MIN_SIZE}:${HEAVYTAIL_MAX_SIZE}}"

echo "== Synthetic config =="
echo "NODES=$NODES CONNS_INCAST=$CONNS_INCAST FLOWSIZE_INCAST=$FLOWSIZE_INCAST EXTRA_START_US=$EXTRA_START_US"
echo "A2A_CONNS=$A2A_CONNS A2A_GROUPSIZE=$A2A_GROUPSIZE A2A_PARALLEL=$A2A_PARALLEL FLOWSIZE_A2A=$FLOWSIZE_A2A EXTRA_START_US_A2A=$EXTRA_START_US_A2A"
echo "ROUTE_STRAT=$ROUTE_STRAT ROUTE_PATHS=$ROUTE_PATHS ROUTE_PATH_BURST=$ROUTE_PATH_BURST END_US_INCAST=$END_US_INCAST END_US_A2A=$END_US_A2A SEED=$SEED"
echo "PROTOCOL=$PROTOCOL SIM_BIN=$SIM_BIN"
echo "DATASET=${DATASET:-<all>}"
echo "GENERATE_FLOW_SIZE_SWEEP=$GENERATE_FLOW_SIZE_SWEEP FLOW_SIZE_SWEEP_VALUES=${FLOW_SIZE_SWEEP_LIST[*]:-<none>}"
echo "GENERATE_BURST_SWEEP=$GENERATE_BURST_SWEEP BURST_SWEEP_VALUES=${BURST_SWEEP_LIST[*]:-<none>}"
echo "BURST_MONO_PACKETS=$BURST_MONO_PACKETS"
echo "GENERATE_PARETO_SKEW_SWEEP=$GENERATE_PARETO_SKEW_SWEEP PARETO_ALPHA_SWEEP_VALUES=${PARETO_ALPHA_SWEEP_LIST[*]:-<none>}"
echo "PARETO_SKEW_BASE_XM=$PARETO_SKEW_BASE_XM PARETO_SKEW_MAX_SIZE=$PARETO_SKEW_MAX_SIZE"
echo "SKEW_TARGET_TOTAL_BYTES_INCAST=$SKEW_TARGET_TOTAL_BYTES_INCAST SKEW_TARGET_TOTAL_BYTES_A2A=$SKEW_TARGET_TOTAL_BYTES_A2A"
echo "GENERATE_HEAVYTAIL_SIGMA_SWEEP=$GENERATE_HEAVYTAIL_SIGMA_SWEEP HEAVYTAIL_SIGMA_SWEEP_VALUES=${HEAVYTAIL_SIGMA_SWEEP_LIST[*]:-<none>}"
echo "HEAVYTAIL_MIN_SIZE=$HEAVYTAIL_MIN_SIZE HEAVYTAIL_MAX_SIZE=$HEAVYTAIL_MAX_SIZE HEAVYTAIL_SPEC=$HEAVYTAIL_SPEC"
echo "GENERATE_TEMPORAL_SWEEP=$GENERATE_TEMPORAL_SWEEP TEMPORAL_SWEEP_VALUES=${TEMPORAL_SWEEP_LIST[*]:-<none>}"
echo "TEMPORAL_BASE_EXTRA_START_US=$TEMPORAL_BASE_EXTRA_START_US TEMPORAL_BASE_EXTRA_START_US_A2A=$TEMPORAL_BASE_EXTRA_START_US_A2A"
echo "BURST_BASE_EXTRA_START_US=$BURST_BASE_EXTRA_START_US BURST_BASE_EXTRA_START_US_A2A=$BURST_BASE_EXTRA_START_US_A2A"
echo "TEMPORAL_END_MARGIN_US=$TEMPORAL_END_MARGIN_US"
echo "FLOW_SWEEP_PKT_BYTES=$FLOW_SWEEP_PKT_BYTES"
echo "FLOW_SWEEP_CONNS_INCAST=$FLOW_SWEEP_CONNS_INCAST FLOW_SWEEP_A2A_CONNS=$FLOW_SWEEP_A2A_CONNS FLOW_SWEEP_A2A_GROUPSIZE=$FLOW_SWEEP_A2A_GROUPSIZE FLOW_SWEEP_A2A_PARALLEL=$FLOW_SWEEP_A2A_PARALLEL"
echo "FLOW_SWEEP_END_US_INCAST=${FLOW_SWEEP_END_US_INCAST:-<auto>} FLOW_SWEEP_END_US_A2A=${FLOW_SWEEP_END_US_A2A:-<auto>}"
echo "FLOW_SWEEP_END_US_INCAST_BASE=$FLOW_SWEEP_END_US_INCAST_BASE FLOW_SWEEP_END_US_A2A_BASE=$FLOW_SWEEP_END_US_A2A_BASE"
echo

run_gen() {
  "$@" >/dev/null
}

cm_total_bytes() {
  local cm_file="$1"
  python3 - "$cm_file" <<'PY'
import re
import sys

path = sys.argv[1]
total = 0
with open(path, encoding="utf-8", errors="replace") as f:
  for line in f:
    m = re.search(r"\bsize\s+(\d+)\b", line)
    if m:
      total += int(m.group(1))
print(total)
PY
}

normalize_cm_total_bytes() {
  local cm_file="$1"
  local target_total="$2"
  if [[ ! -f "$cm_file" ]]; then
  return
  fi
  if (( target_total <= 0 )); then
  return
  fi
  python3 - "$cm_file" "$target_total" <<'PY'
import math
import re
import sys

path = sys.argv[1]
target = int(sys.argv[2])
size_re = re.compile(r"(\bsize\s+)(\d+)(\b)")

with open(path, encoding="utf-8", errors="replace") as f:
  lines = f.readlines()

idx = []
vals = []
for i, line in enumerate(lines):
  m = size_re.search(line)
  if not m:
    continue
  idx.append(i)
  vals.append(int(m.group(2)))

if not vals:
  sys.exit(0)

cur = sum(vals)
if cur <= 0:
  sys.exit(0)

scale = target / cur
scaled = [max(1, int(round(v * scale))) for v in vals]
delta = target - sum(scaled)
if delta != 0:
  order = sorted(range(len(scaled)), key=lambda j: scaled[j], reverse=(delta < 0))
  step = 1 if delta > 0 else -1
  left = abs(delta)
  k = 0
  while left > 0 and order:
    j = order[k % len(order)]
    nv = scaled[j] + step
    if nv >= 1:
      scaled[j] = nv
      left -= 1
    k += 1

for i, nv in zip(idx, scaled):
  lines[i] = size_re.sub(rf"\g<1>{nv}\g<3>", lines[i], count=1)

with open(path, "w", encoding="utf-8") as f:
  f.writelines(lines)
PY
}

TOTAL_WRITTEN_LINES=0

should_process() {
  local name="$1"
  if [[ -n "$DATASET_FAMILY_PREFIX" ]]; then
    case "$DATASET_FAMILY_KIND" in
      mono)
        [[ "$name" =~ ^(incast|a2a)_mono_[0-9]+$ ]] && [[ "$name" == "$DATASET_FAMILY_PREFIX"* ]]
        return
        ;;
      mono_burst)
        [[ "$name" =~ ^(incast|a2a)_mono_burst_[0-9]+$ ]] && [[ "$name" == "$DATASET_FAMILY_PREFIX"* ]]
        return
        ;;
      pareto_alpha)
        [[ "$name" =~ ^(incast|a2a)_pareto_alpha_[0-9]+(p[0-9]+)?$ ]] && [[ "$name" == "$DATASET_FAMILY_PREFIX"* ]]
        return
        ;;
      heavytail_temp)
        [[ "$name" =~ ^(incast|a2a)_heavytail_temp_[0-9]+$ ]] && [[ "$name" == "$DATASET_FAMILY_PREFIX"* ]]
        return
        ;;
      heavytail_sigma)
        [[ "$name" =~ ^(incast|a2a)_heavytail_sigma_[0-9]+(p[0-9]+)?$ ]] && [[ "$name" == "$DATASET_FAMILY_PREFIX"* ]]
        return
        ;;
    esac
  fi
  [[ -z "$DATASET" || "$DATASET" == "$name" ]]
}

echo "== Generating traffic matrices =="
if should_process "incast_mono"; then
  run_gen python3 sim/datacenter/connection_matrices/gen_incast.py "$INC_CM" "$NODES" "$CONNS_INCAST" "$FLOWSIZE_INCAST" "$EXTRA_START_US" "$SEED" fixed
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
if should_process "a2a_mono"; then
  if (( A2A_PARALLEL == 1 )); then
    run_gen python3 sim/datacenter/connection_matrices/gen_serial_alltoall.py "$A2A_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$FLOWSIZE_A2A" "$EXTRA_START_US_A2A" "$SEED"
  else
    run_gen python3 sim/datacenter/connection_matrices/gen_serialn_alltoall.py "$A2A_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$A2A_PARALLEL" "$FLOWSIZE_A2A" "$EXTRA_START_US_A2A" "$SEED"
  fi
fi

if should_process "incast_bimodal"; then
  run_gen python3 sim/datacenter/connection_matrices/gen_incast.py "$INCAST_BIMODAL_CM" "$NODES" "$CONNS_INCAST" "$FLOWSIZE_INCAST" "$EXTRA_START_US" "$SEED" "$BIMODAL_SPEC"
fi
if should_process "incast_pareto"; then
  run_gen python3 sim/datacenter/connection_matrices/gen_incast.py "$INCAST_PARETO_CM" "$NODES" "$CONNS_INCAST" "$FLOWSIZE_INCAST" "$EXTRA_START_US" "$SEED" "$PARETO_SPEC"
fi
if should_process "incast_heavytail"; then
  run_gen python3 sim/datacenter/connection_matrices/gen_incast.py "$INCAST_HEAVYTAIL_CM" "$NODES" "$CONNS_INCAST" "$FLOWSIZE_INCAST" "$EXTRA_START_US" "$SEED" "$HEAVYTAIL_SPEC"
fi
if should_process "incast_exponential_skewed"; then
  run_gen python3 sim/datacenter/connection_matrices/gen_incast.py "$INCAST_EXPONENTIAL_SKEWED_CM" "$NODES" "$CONNS_INCAST" "$FLOWSIZE_INCAST" "$EXTRA_START_US" "$SEED" "$EXPONENTIAL_SKEWED_SPEC"
fi

if (( A2A_PARALLEL == 1 )); then
  if should_process "a2a_bimodal"; then
    run_gen python3 sim/datacenter/connection_matrices/gen_serial_alltoall.py "$A2A_BIMODAL_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$FLOWSIZE_A2A" "$EXTRA_START_US_A2A" "$SEED" "$BIMODAL_SPEC"
  fi
  if should_process "a2a_pareto"; then
    run_gen python3 sim/datacenter/connection_matrices/gen_serial_alltoall.py "$A2A_PARETO_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$FLOWSIZE_A2A" "$EXTRA_START_US_A2A" "$SEED" "$PARETO_SPEC"
  fi
  if should_process "a2a_heavytail"; then
    run_gen python3 sim/datacenter/connection_matrices/gen_serial_alltoall.py "$A2A_HEAVYTAIL_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$FLOWSIZE_A2A" "$EXTRA_START_US_A2A" "$SEED" "$HEAVYTAIL_SPEC"
  fi
  if should_process "a2a_exponential_skewed"; then
    run_gen python3 sim/datacenter/connection_matrices/gen_serial_alltoall.py "$A2A_EXPONENTIAL_SKEWED_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$FLOWSIZE_A2A" "$EXTRA_START_US_A2A" "$SEED" "$EXPONENTIAL_SKEWED_SPEC"
  fi
else
  if should_process "a2a_bimodal"; then
    run_gen python3 sim/datacenter/connection_matrices/gen_serialn_alltoall.py "$A2A_BIMODAL_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$A2A_PARALLEL" "$FLOWSIZE_A2A" "$EXTRA_START_US_A2A" "$SEED" "$BIMODAL_SPEC"
  fi
  if should_process "a2a_pareto"; then
    run_gen python3 sim/datacenter/connection_matrices/gen_serialn_alltoall.py "$A2A_PARETO_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$A2A_PARALLEL" "$FLOWSIZE_A2A" "$EXTRA_START_US_A2A" "$SEED" "$PARETO_SPEC"
  fi
  if should_process "a2a_heavytail"; then
    run_gen python3 sim/datacenter/connection_matrices/gen_serialn_alltoall.py "$A2A_HEAVYTAIL_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$A2A_PARALLEL" "$FLOWSIZE_A2A" "$EXTRA_START_US_A2A" "$SEED" "$HEAVYTAIL_SPEC"
  fi
  if should_process "a2a_exponential_skewed"; then
    run_gen python3 sim/datacenter/connection_matrices/gen_serialn_alltoall.py "$A2A_EXPONENTIAL_SKEWED_CM" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$A2A_PARALLEL" "$FLOWSIZE_A2A" "$EXTRA_START_US_A2A" "$SEED" "$EXPONENTIAL_SKEWED_SPEC"
  fi
fi

if [[ "$GENERATE_PARETO_SKEW_SWEEP" == "1" ]]; then
  echo
  echo "== Generating Pareto skew sweep matrices (alpha) =="

  inc_target="$SKEW_TARGET_TOTAL_BYTES_INCAST"
  a2a_target="$SKEW_TARGET_TOTAL_BYTES_A2A"
  if (( inc_target <= 0 )) && [[ -f "$INCAST_PARETO_CM" ]]; then
    inc_target="$(cm_total_bytes "$INCAST_PARETO_CM")"
  fi
  if (( a2a_target <= 0 )) && [[ -f "$A2A_PARETO_CM" ]]; then
    a2a_target="$(cm_total_bytes "$A2A_PARETO_CM")"
  fi

  for alpha in "${PARETO_ALPHA_SWEEP_LIST[@]:-}"; do
    [[ -n "$alpha" ]] || continue
    alpha_tok="${alpha//./p}"
    spec="pareto:${PARETO_SKEW_BASE_XM}:${alpha}:${PARETO_SKEW_MAX_SIZE}"
    inc_cm="$CM_DIR/incast_pareto_alpha_${alpha_tok}.cm"
    a2a_cm="$CM_DIR/a2a_pareto_alpha_${alpha_tok}.cm"

    if should_process "incast_pareto_alpha_${alpha_tok}"; then
      run_gen python3 sim/datacenter/connection_matrices/gen_incast.py "$inc_cm" "$NODES" "$CONNS_INCAST" "$FLOWSIZE_INCAST" "$EXTRA_START_US" "$SEED" "$spec"
      normalize_cm_total_bytes "$inc_cm" "$inc_target"
    fi
    if should_process "a2a_pareto_alpha_${alpha_tok}"; then
      if (( A2A_PARALLEL == 1 )); then
        run_gen python3 sim/datacenter/connection_matrices/gen_serial_alltoall.py "$a2a_cm" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$FLOWSIZE_A2A" "$EXTRA_START_US_A2A" "$SEED" "$spec"
      else
        run_gen python3 sim/datacenter/connection_matrices/gen_serialn_alltoall.py "$a2a_cm" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$A2A_PARALLEL" "$FLOWSIZE_A2A" "$EXTRA_START_US_A2A" "$SEED" "$spec"
      fi
      normalize_cm_total_bytes "$a2a_cm" "$a2a_target"
    fi
  done

fi

if [[ "$GENERATE_FLOW_SIZE_SWEEP" == "1" ]]; then
  echo "== Generating mono flow-size sweep matrices =="
  # When FLOW_SWEEP_NORMALIZE_PKTS=1: total packets = FLOW_SWEEP_CONNS_INCAST * FLOW_SWEEP_BASE_PKTS
  # is kept constant across all N by scaling conns inversely with N. This lets cache performance
  # be compared fairly across different per-flow sizes (temporal locality proxy).
  for fs in "${FLOW_SIZE_SWEEP_LIST[@]}"; do
    flow_bytes=$((fs * FLOW_SWEEP_PKT_BYTES))
    inc_cm="$CM_DIR/incast_mono_${fs}.cm"
    a2a_cm="$CM_DIR/a2a_mono_${fs}.cm"

    if [[ "$FLOW_SWEEP_NORMALIZE_PKTS" == "1" ]]; then
      # conns = BASE_CONNS * BASE_PKTS / N, clamped to [MIN_CONNS, NODES-1]
      _norm_conns_incast=$(( FLOW_SWEEP_CONNS_INCAST * FLOW_SWEEP_BASE_PKTS / fs ))
      if (( _norm_conns_incast > NODES - 1 )); then _norm_conns_incast=$((NODES - 1)); fi
      if (( _norm_conns_incast < FLOW_SWEEP_MIN_CONNS_INCAST )); then _norm_conns_incast="$FLOW_SWEEP_MIN_CONNS_INCAST"; fi

      _base_groups=$(( FLOW_SWEEP_A2A_CONNS / FLOW_SWEEP_A2A_GROUPSIZE ))
      _norm_groups=$(( _base_groups * FLOW_SWEEP_BASE_PKTS / fs ))
      if (( _norm_groups < 1 )); then _norm_groups=1; fi
      _max_a2a_groups=$(( NODES / FLOW_SWEEP_A2A_GROUPSIZE ))
      if (( _norm_groups > _max_a2a_groups )); then _norm_groups=$_max_a2a_groups; fi
      _norm_conns_a2a=$(( _norm_groups * FLOW_SWEEP_A2A_GROUPSIZE ))
    else
      _norm_conns_incast="$FLOW_SWEEP_CONNS_INCAST"
      _norm_conns_a2a="$FLOW_SWEEP_A2A_CONNS"
    fi

    if should_process "incast_mono_${fs}"; then
      run_gen python3 sim/datacenter/connection_matrices/gen_incast.py "$inc_cm" "$NODES" "$_norm_conns_incast" "$flow_bytes" "$FLOW_SWEEP_EXTRA_START_US" "$SEED" fixed
    fi

    if should_process "a2a_mono_${fs}"; then
      if (( FLOW_SWEEP_A2A_PARALLEL == 1 )); then
        run_gen python3 sim/datacenter/connection_matrices/gen_serial_alltoall.py "$a2a_cm" "$NODES" "$_norm_conns_a2a" "$FLOW_SWEEP_A2A_GROUPSIZE" "$flow_bytes" "$FLOW_SWEEP_EXTRA_START_US_A2A" "$SEED"
      else
        run_gen python3 sim/datacenter/connection_matrices/gen_serialn_alltoall.py "$a2a_cm" "$NODES" "$_norm_conns_a2a" "$FLOW_SWEEP_A2A_GROUPSIZE" "$FLOW_SWEEP_A2A_PARALLEL" "$flow_bytes" "$FLOW_SWEEP_EXTRA_START_US_A2A" "$SEED"
      fi
    fi
  done
fi

run_htsim() {
  local name="$1"
  local cm_file="$2"
  local conns="$3"
  local end_us="${4:-$END_US_INCAST}"
  local path_burst_override="${5:-}"
  local out_file="$OUT_DIR/log_${name}.txt"
  local raw_file="$RUN_DIR/${name}.raw.log"

  if ! should_process "$name"; then
    return
  fi
  if [[ ! -f "$cm_file" ]]; then
    echo "Skipping ${name}: missing matrix ${cm_file}"
    return
  fi

  local proto_label
  proto_label="$(printf '%s' "$PROTOCOL" | tr '[:lower:]' '[:upper:]')"
  echo "== Running HTSIM ${proto_label} for ${name}; writing to ${out_file} =="

  local cmd=("$SIM_BIN" -nodes "$NODES" -conns "$conns" -tm "$cm_file" -strat "$ROUTE_STRAT" -paths "$ROUTE_PATHS" -end "$end_us")
  if [[ "$PROTOCOL" == "ndp" ]]; then
    local path_burst="$ROUTE_PATH_BURST"
    if [[ -n "$path_burst_override" ]]; then
      path_burst="$path_burst_override"
    fi
    cmd+=(-path_burst "$path_burst")
  fi

  if "${cmd[@]}" 1> "$raw_file" 2> "$out_file"; then
    :
  else
    local rc=$?
    echo "ERROR: HTSIM ${proto_label} failed for ${name} (exit code ${rc})." >&2
    echo "  stdout log: ${raw_file}" >&2
    echo "  stderr log: ${out_file}" >&2
    if [[ -s "$raw_file" ]]; then
      echo "---- tail of stdout (${raw_file}) ----" >&2
      tail -n 40 "$raw_file" >&2
    fi
    if [[ -s "$out_file" ]]; then
      echo "---- tail of stderr (${out_file}) ----" >&2
      tail -n 40 "$out_file" >&2
    fi
    return "$rc"
  fi

  local line_count
  line_count=$(wc -l < "$out_file" | tr -d '[:space:]')
  TOTAL_WRITTEN_LINES=$((TOTAL_WRITTEN_LINES + line_count))
  echo "Wrote (${line_count} lines)"
}

run_htsim "incast_mono" "$INC_CM" "$CONNS_INCAST"
run_htsim "a2a_mono" "$A2A_CM" "$A2A_CONNS" "$END_US_A2A"
run_htsim "incast_bimodal" "$INCAST_BIMODAL_CM" "$CONNS_INCAST"
run_htsim "a2a_bimodal" "$A2A_BIMODAL_CM" "$A2A_CONNS" "$END_US_A2A"
run_htsim "incast_pareto" "$INCAST_PARETO_CM" "$CONNS_INCAST"
run_htsim "a2a_pareto" "$A2A_PARETO_CM" "$A2A_CONNS" "$END_US_A2A"
run_htsim "incast_heavytail" "$INCAST_HEAVYTAIL_CM" "$CONNS_INCAST"
run_htsim "a2a_heavytail" "$A2A_HEAVYTAIL_CM" "$A2A_CONNS" "$END_US_A2A"
run_htsim "incast_exponential_skewed" "$INCAST_EXPONENTIAL_SKEWED_CM" "$CONNS_INCAST"
run_htsim "a2a_exponential_skewed" "$A2A_EXPONENTIAL_SKEWED_CM" "$A2A_CONNS" "$END_US_A2A"

if [[ "$GENERATE_PARETO_SKEW_SWEEP" == "1" ]]; then
  echo
  echo "== Running HTSIM for Pareto skew sweep datasets =="
  for alpha in "${PARETO_ALPHA_SWEEP_LIST[@]:-}"; do
    [[ -n "$alpha" ]] || continue
    alpha_tok="${alpha//./p}"
    run_htsim "incast_pareto_alpha_${alpha_tok}" "$CM_DIR/incast_pareto_alpha_${alpha_tok}.cm" "$CONNS_INCAST"
    run_htsim "a2a_pareto_alpha_${alpha_tok}" "$CM_DIR/a2a_pareto_alpha_${alpha_tok}.cm" "$A2A_CONNS" "$END_US_A2A"
  done
fi

if [[ "$GENERATE_HEAVYTAIL_SIGMA_SWEEP" == "1" ]]; then
  echo
  echo "== Generating heavytail sigma sweep matrices =="
  for sigma in "${HEAVYTAIL_SIGMA_SWEEP_LIST[@]:-}"; do
    [[ -n "$sigma" ]] || continue
    sigma_tok="${sigma//./p}"
    spec="heavytail:${sigma}:${HEAVYTAIL_MIN_SIZE}:${HEAVYTAIL_MAX_SIZE}"
    inc_cm="$CM_DIR/incast_heavytail_sigma_${sigma_tok}.cm"
    a2a_cm="$CM_DIR/a2a_heavytail_sigma_${sigma_tok}.cm"

    if should_process "incast_heavytail_sigma_${sigma_tok}"; then
      run_gen python3 sim/datacenter/connection_matrices/gen_incast.py "$inc_cm" "$NODES" "$CONNS_INCAST" "$FLOWSIZE_INCAST" "$EXTRA_START_US" "$SEED" "$spec"
    fi
    if should_process "a2a_heavytail_sigma_${sigma_tok}"; then
      if (( A2A_PARALLEL == 1 )); then
        run_gen python3 sim/datacenter/connection_matrices/gen_serial_alltoall.py "$a2a_cm" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$FLOWSIZE_A2A" "$EXTRA_START_US_A2A" "$SEED" "$spec"
      else
        run_gen python3 sim/datacenter/connection_matrices/gen_serialn_alltoall.py "$a2a_cm" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$A2A_PARALLEL" "$FLOWSIZE_A2A" "$EXTRA_START_US_A2A" "$SEED" "$spec"
      fi
    fi
  done

  echo
  echo "== Running HTSIM for heavytail sigma sweep datasets =="
  for sigma in "${HEAVYTAIL_SIGMA_SWEEP_LIST[@]:-}"; do
    [[ -n "$sigma" ]] || continue
    sigma_tok="${sigma//./p}"
    run_htsim "incast_heavytail_sigma_${sigma_tok}" "$CM_DIR/incast_heavytail_sigma_${sigma_tok}.cm" "$CONNS_INCAST"
    run_htsim "a2a_heavytail_sigma_${sigma_tok}" "$CM_DIR/a2a_heavytail_sigma_${sigma_tok}.cm" "$A2A_CONNS" "$END_US_A2A"
  done
fi

if [[ "$GENERATE_FLOW_SIZE_SWEEP" == "1" ]]; then
  echo
  echo "== Running HTSIM for mono flow-size sweep datasets =="
  for fs in "${FLOW_SIZE_SWEEP_LIST[@]}"; do
    if [[ "$FLOW_SWEEP_NORMALIZE_PKTS" == "1" ]]; then
      # Constant end time across all N: total bytes is constant so throughput duration is similar
      sweep_end_us_incast="${FLOW_SWEEP_END_US_INCAST:-$((FLOW_SWEEP_END_US_INCAST_BASE * FLOW_SWEEP_BASE_PKTS))}"
      sweep_end_us_a2a="${FLOW_SWEEP_END_US_A2A:-$((FLOW_SWEEP_END_US_A2A_BASE * FLOW_SWEEP_BASE_PKTS))}"
      _norm_conns_incast=$(( FLOW_SWEEP_CONNS_INCAST * FLOW_SWEEP_BASE_PKTS / fs ))
      if (( _norm_conns_incast > NODES - 1 )); then _norm_conns_incast=$((NODES - 1)); fi
      if (( _norm_conns_incast < FLOW_SWEEP_MIN_CONNS_INCAST )); then _norm_conns_incast="$FLOW_SWEEP_MIN_CONNS_INCAST"; fi
      _base_groups=$(( FLOW_SWEEP_A2A_CONNS / FLOW_SWEEP_A2A_GROUPSIZE ))
      _norm_groups=$(( _base_groups * FLOW_SWEEP_BASE_PKTS / fs ))
      if (( _norm_groups < 1 )); then _norm_groups=1; fi
      _max_a2a_groups=$(( NODES / FLOW_SWEEP_A2A_GROUPSIZE ))
      if (( _norm_groups > _max_a2a_groups )); then _norm_groups=$_max_a2a_groups; fi
      _norm_conns_a2a=$(( _norm_groups * FLOW_SWEEP_A2A_GROUPSIZE ))
    else
      sweep_end_us_incast="${FLOW_SWEEP_END_US_INCAST:-$((FLOW_SWEEP_END_US_INCAST_BASE * fs))}"
      sweep_end_us_a2a="${FLOW_SWEEP_END_US_A2A:-$((FLOW_SWEEP_END_US_A2A_BASE * fs))}"
      _norm_conns_incast="$FLOW_SWEEP_CONNS_INCAST"
      _norm_conns_a2a="$FLOW_SWEEP_A2A_CONNS"
    fi
    run_htsim "incast_mono_${fs}" "$CM_DIR/incast_mono_${fs}.cm" "$_norm_conns_incast" "$sweep_end_us_incast"
    run_htsim "a2a_mono_${fs}" "$CM_DIR/a2a_mono_${fs}.cm" "$_norm_conns_a2a" "$sweep_end_us_a2a"
  done
fi

if [[ "$GENERATE_BURST_SWEEP" == "1" ]]; then
  echo
  echo "== Running HTSIM for mono burstiness sweep datasets (fixed packets=${BURST_MONO_PACKETS}) =="
  burst_flow_bytes=$((BURST_MONO_PACKETS * FLOW_SWEEP_PKT_BYTES))
  for bs in "${BURST_SWEEP_LIST[@]}"; do
    if [[ "$PROTOCOL" == "ndp" ]]; then
      inc_cm="$CM_DIR/incast_mono_burst_base.cm"
      a2a_cm="$CM_DIR/a2a_mono_burst_base.cm"

      if should_process "incast_mono_burst_${bs}"; then
        run_gen python3 sim/datacenter/connection_matrices/gen_incast.py "$inc_cm" "$NODES" "$CONNS_INCAST" "$burst_flow_bytes" "$EXTRA_START_US" "$SEED" fixed
      fi
      if should_process "a2a_mono_burst_${bs}"; then
        if (( A2A_PARALLEL == 1 )); then
          run_gen python3 sim/datacenter/connection_matrices/gen_serial_alltoall.py "$a2a_cm" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$burst_flow_bytes" "$EXTRA_START_US_A2A" "$SEED"
        else
          run_gen python3 sim/datacenter/connection_matrices/gen_serialn_alltoall.py "$a2a_cm" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$A2A_PARALLEL" "$burst_flow_bytes" "$EXTRA_START_US_A2A" "$SEED"
        fi
      fi

      run_htsim "incast_mono_burst_${bs}" "$inc_cm" "$CONNS_INCAST" "$END_US_INCAST" "$bs"
      run_htsim "a2a_mono_burst_${bs}" "$a2a_cm" "$A2A_CONNS" "$END_US_A2A" "$bs"
      continue
    fi

    inc_cm="$CM_DIR/incast_mono_burst_${bs}.cm"
    a2a_cm="$CM_DIR/a2a_mono_burst_${bs}.cm"
    inc_extra=$((BURST_BASE_EXTRA_START_US / bs))
    a2a_extra=$((BURST_BASE_EXTRA_START_US_A2A / bs))
    if (( inc_extra < 1 )); then inc_extra=1; fi
    if (( a2a_extra < 1 )); then a2a_extra=1; fi

    if should_process "incast_mono_burst_${bs}"; then
      run_gen python3 sim/datacenter/connection_matrices/gen_incast.py "$inc_cm" "$NODES" "$CONNS_INCAST" "$burst_flow_bytes" "$inc_extra" "$SEED" fixed
    fi
    if should_process "a2a_mono_burst_${bs}"; then
      if (( A2A_PARALLEL == 1 )); then
        run_gen python3 sim/datacenter/connection_matrices/gen_serial_alltoall.py "$a2a_cm" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$burst_flow_bytes" "$a2a_extra" "$SEED"
      else
        run_gen python3 sim/datacenter/connection_matrices/gen_serialn_alltoall.py "$a2a_cm" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$A2A_PARALLEL" "$burst_flow_bytes" "$a2a_extra" "$SEED"
      fi
    fi

    run_htsim "incast_mono_burst_${bs}" "$inc_cm" "$CONNS_INCAST" "$END_US_INCAST"
    run_htsim "a2a_mono_burst_${bs}" "$a2a_cm" "$A2A_CONNS" "$END_US_A2A"
  done
fi

if [[ "$GENERATE_TEMPORAL_SWEEP" == "1" ]]; then
  echo
  echo "== Generating temporal-locality sweep datasets (heavytail_temp) =="
  # Temporal locality is controlled by flow size: multiplier tv scales the heavytail median
  # (min_size) so larger tv -> longer flows -> more consecutive same-path packets -> better
  # cache suppression. Start spread also scales with tv so concurrency stays roughly constant.
  for tv in "${TEMPORAL_SWEEP_LIST[@]}"; do
    inc_cm="$CM_DIR/incast_heavytail_temp_${tv}.cm"
    a2a_cm="$CM_DIR/a2a_heavytail_temp_${tv}.cm"
    inc_extra=$((TEMPORAL_BASE_EXTRA_START_US * tv))
    a2a_extra=$((TEMPORAL_BASE_EXTRA_START_US_A2A * tv))
    temporal_end_us_a2a=$((END_US_A2A + a2a_extra + TEMPORAL_END_MARGIN_US))
    # Scale median by tv; heavy tail max stays fixed so very large flows are always possible
    temp_min_size=$((HEAVYTAIL_TEMP_MIN_SIZE * tv))
    temp_spec="heavytail:${HEAVYTAIL_TEMP_SIGMA}:${temp_min_size}:${HEAVYTAIL_TEMP_MAX_SIZE}"

    if should_process "incast_heavytail_temp_${tv}"; then
      run_gen python3 sim/datacenter/connection_matrices/gen_incast.py "$inc_cm" "$NODES" "$CONNS_INCAST" "$FLOWSIZE_INCAST" "$inc_extra" "$SEED" "$temp_spec"
    fi
    if should_process "a2a_heavytail_temp_${tv}"; then
      if (( A2A_PARALLEL == 1 )); then
        run_gen python3 sim/datacenter/connection_matrices/gen_serial_alltoall.py "$a2a_cm" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$FLOWSIZE_A2A" "$a2a_extra" "$SEED" "$temp_spec"
      else
        run_gen python3 sim/datacenter/connection_matrices/gen_serialn_alltoall.py "$a2a_cm" "$NODES" "$A2A_CONNS" "$A2A_GROUPSIZE" "$A2A_PARALLEL" "$FLOWSIZE_A2A" "$a2a_extra" "$SEED" "$temp_spec"
      fi
    fi

    run_htsim "incast_heavytail_temp_${tv}" "$inc_cm" "$CONNS_INCAST"
    run_htsim "a2a_heavytail_temp_${tv}" "$a2a_cm" "$A2A_CONNS" "$temporal_end_us_a2a"
  done
fi

echo
echo "Done. total_written_lines=$TOTAL_WRITTEN_LINES"
