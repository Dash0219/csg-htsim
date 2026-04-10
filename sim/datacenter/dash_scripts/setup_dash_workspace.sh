#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash sim/datacenter/dash_scripts/setup_dash_workspace.sh [options]

Options:
  -n, --dry-run           Print directories/instructions but do not create folders
  -h, --help              Show this help

What this script does:
  - Creates the expected dash_dataset/ and dash_results/ folder tree used by wrappers.
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
DC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$DC_ROOT"

DIRS=(
  "dash_dataset/imc/univ1/univ1_trace_pcap"
  "dash_dataset/imc/univ2/univ2_trace_pcap"
  "dash_dataset/mawi"
  "dash_dataset/gnnet/gnnet-ch23-dataset-mb/pkts_info"
  "dash_dataset/gnnet/gnnet_trace_int"
  "dash_dataset/synthetic"

  "dash_results/imc/univ1/cache_sim/source_seen/plots"
  "dash_results/imc/univ1/flow_distribution/plots"
  "dash_results/imc/univ1/flow_stats"
  "dash_results/imc/univ1/temporal_locality/plots"

  "dash_results/imc/univ2/cache_sim/source_seen/plots"
  "dash_results/imc/univ2/flow_distribution/plots"
  "dash_results/imc/univ2/flow_stats"
  "dash_results/imc/univ2/temporal_locality/plots"

  "dash_results/mawi/cache_sim/source_seen/plots"
  "dash_results/mawi/flow_distribution/plots"
  "dash_results/mawi/flow_stats"
  "dash_results/mawi/temporal_locality/plots"

  "dash_results/gnnet/cache_sim/source_seen/plots"
  "dash_results/gnnet/flow_distribution/plots"
  "dash_results/gnnet/flow_stats"
  "dash_results/gnnet/temporal_locality/plots"

  "dash_results/synthetic/connection_matrices"
  "dash_results/synthetic/raw_logs"
  "dash_results/synthetic/cache_sim/route_changes/plots"
  "dash_results/synthetic/cache_sim/source_seen/plots"
  "dash_results/synthetic/flow_distribution/plots"
  "dash_results/synthetic/flow_stats"
  "dash_results/synthetic/temporal_locality/plots"
)

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[dry-run] would create:"
  printf '  %s\n' "${DIRS[@]}"
else
  mkdir -p "${DIRS[@]}"
  echo "Created directory tree under: $DC_ROOT"
fi

cat <<'EOF'

Place real datasets here:

1) IMC
   - Univ1 pcaps/text input: dash_dataset/imc/univ1/univ1_trace_pcap/
   - Univ2 pcaps/text input: dash_dataset/imc/univ2/univ2_trace_pcap/

2) MAWI
   - Raw dump: dash_dataset/mawi/200803180000.dump
   - Optional pre-converted text dump: dash_dataset/mawi/200803180000.dump.txt

3) GNNet
  - Dataset root: dash_dataset/gnnet/gnnet-ch23-dataset-mb/
  - Required packet pickles: dash_dataset/gnnet/gnnet-ch23-dataset-mb/pkts_info/delays_info_path.p.*

4) Synthetic
   - No external dataset needed.
   - Generate logs with: bash dash_scripts/run_htsim_synthetic.sh

After placing data, run pipelines from sim/datacenter:
  python3 dash_scripts/run_imc_pipeline.py univ1
  python3 dash_scripts/run_imc_pipeline.py univ2
  python3 dash_scripts/run_mawi_pipeline.py
  python3 dash_scripts/run_gnnet_pipeline.py
EOF
