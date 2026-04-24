#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash fyp/dash_scripts/setup_dash_workspace.sh [options]

Options:
  -n, --dry-run           Print directories/instructions but do not create folders
  -h, --help              Show this help

What this script does:
  - Creates the expected fyp/dash_dataset/ and fyp/dash_results/ folder tree used by wrappers.
  - Prints exactly where to place real IMC/MAWI datasets.
EOF
}

DRY_RUN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

DIRS=(
  "fyp/dash_dataset/imc/univ1/univ1_trace_pcap"
  "fyp/dash_dataset/imc/univ2/univ2_trace_pcap"
  "fyp/dash_dataset/mawi"
  "fyp/dash_dataset/synthetic"
  "fyp/dash_dataset/synthetic/ndp"
  "fyp/dash_dataset/synthetic/hpcc"

  "fyp/dash_results/imc/univ1/cache_sim/source_seen/plots"
  "fyp/dash_results/imc/univ1/cache_sim/source_seen/capacity/plots"
  "fyp/dash_results/imc/univ1/flow_size/plots"
  "fyp/dash_results/imc/univ1/flow_lifetime/plots"
  "fyp/dash_results/imc/univ1/ttl_window/plots"
  "fyp/dash_results/imc/univ1/flow_stats"
  "fyp/dash_results/imc/univ1/temporal_locality/plots"

  "fyp/dash_results/imc/univ2/cache_sim/source_seen/plots"
  "fyp/dash_results/imc/univ2/cache_sim/source_seen/capacity/plots"
  "fyp/dash_results/imc/univ2/flow_size/plots"
  "fyp/dash_results/imc/univ2/flow_lifetime/plots"
  "fyp/dash_results/imc/univ2/ttl_window/plots"
  "fyp/dash_results/imc/univ2/flow_stats"
  "fyp/dash_results/imc/univ2/temporal_locality/plots"

  "fyp/dash_results/mawi/cache_sim/source_seen/plots"
  "fyp/dash_results/mawi/cache_sim/source_seen/capacity/plots"
  "fyp/dash_results/mawi/flow_size/plots"
  "fyp/dash_results/mawi/flow_lifetime/plots"
  "fyp/dash_results/mawi/ttl_window/plots"
  "fyp/dash_results/mawi/flow_stats"
  "fyp/dash_results/mawi/temporal_locality/plots"

  "fyp/dash_results/synthetic/ndp/connection_matrices"
  "fyp/dash_results/synthetic/ndp/raw_logs"
  "fyp/dash_results/synthetic/ndp/cache_sim/congestion/plots"
  "fyp/dash_results/synthetic/ndp/cache_sim/congestion/capacity/plots"
  "fyp/dash_results/synthetic/ndp/cache_sim/route_changes/plots"
  "fyp/dash_results/synthetic/ndp/cache_sim/route_changes/capacity/plots"
  "fyp/dash_results/synthetic/ndp/cache_sim/source_seen/plots"
  "fyp/dash_results/synthetic/ndp/cache_sim/source_seen/capacity/plots"
  "fyp/dash_results/synthetic/ndp/flow_size/plots"
  "fyp/dash_results/synthetic/ndp/flow_lifetime/plots"
  "fyp/dash_results/synthetic/ndp/ttl_window/plots"
  "fyp/dash_results/synthetic/ndp/flow_stats"
  "fyp/dash_results/synthetic/ndp/temporal_locality/plots"

  "fyp/dash_results/synthetic/hpcc/connection_matrices"
  "fyp/dash_results/synthetic/hpcc/raw_logs"
  "fyp/dash_results/synthetic/hpcc/cache_sim/congestion/plots"
  "fyp/dash_results/synthetic/hpcc/cache_sim/congestion/capacity/plots"
  "fyp/dash_results/synthetic/hpcc/cache_sim/route_changes/plots"
  "fyp/dash_results/synthetic/hpcc/cache_sim/route_changes/capacity/plots"
  "fyp/dash_results/synthetic/hpcc/cache_sim/source_seen/plots"
  "fyp/dash_results/synthetic/hpcc/cache_sim/source_seen/capacity/plots"
  "fyp/dash_results/synthetic/hpcc/flow_size/plots"
  "fyp/dash_results/synthetic/hpcc/flow_lifetime/plots"
  "fyp/dash_results/synthetic/hpcc/ttl_window/plots"
  "fyp/dash_results/synthetic/hpcc/flow_stats"
  "fyp/dash_results/synthetic/hpcc/temporal_locality/plots"
)

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[dry-run] would create:"
  printf '  %s\n' "${DIRS[@]}"
else
  mkdir -p "${DIRS[@]}"
  echo "Created directory tree under: $REPO_ROOT"
fi

cat <<'EOF'

Place real datasets here:

1) IMC
   - Univ1 pcaps/text input: fyp/dash_dataset/imc/univ1/univ1_trace_pcap/
   - Univ2 pcaps/text input: fyp/dash_dataset/imc/univ2/univ2_trace_pcap/

2) MAWI
   - Raw dump: fyp/dash_dataset/mawi/200803180000.dump
   - Optional pre-converted text dump: fyp/dash_dataset/mawi/200803180000.dump.txt

3) Synthetic
   - No external dataset needed.
  - Generate logs with: bash fyp/dash_scripts/run_htsim_synthetic.sh --protocol ndp
  - Or for HPCC: bash fyp/dash_scripts/run_htsim_synthetic.sh --protocol hpcc

After placing data, run pipelines from the repository root:
  python3 fyp/dash_scripts/run_imc_pipeline.py univ1
  python3 fyp/dash_scripts/run_imc_pipeline.py univ2
  python3 fyp/dash_scripts/run_mawi_pipeline.py
EOF
