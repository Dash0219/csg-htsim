#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash fyp/scripts/setup_workspace.sh [options]

Options:
  -n, --dry-run           Print directories/instructions but do not create folders
  -h, --help              Show this help

What this script does:
  - Creates the expected fyp/dataset/ and fyp/results/ folder tree used by wrappers.
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
  "fyp/dataset/imc/uni1/uni1_trace_pcap"
  "fyp/dataset/imc/uni2/uni2_trace_pcap"
  "fyp/dataset/mawi"
  "fyp/dataset/synthetic"
  "fyp/dataset/synthetic/ndp"
  "fyp/dataset/synthetic/hpcc"
  "fyp/dataset/synthetic/tcp"

  "fyp/results/imc/uni1/cache_sim/source_seen/plots"
  "fyp/results/imc/uni1/cache_sim/source_seen/capacity/plots"
  "fyp/results/imc/uni1/flow_size/plots"
  "fyp/results/imc/uni1/flow_lifetime/plots"
  "fyp/results/imc/uni1/ttl_window/plots"
  "fyp/results/imc/uni1/flow_stats"
  "fyp/results/imc/uni1/flow_concurrency/plots"

  "fyp/results/imc/uni2/cache_sim/source_seen/plots"
  "fyp/results/imc/uni2/cache_sim/source_seen/capacity/plots"
  "fyp/results/imc/uni2/flow_size/plots"
  "fyp/results/imc/uni2/flow_lifetime/plots"
  "fyp/results/imc/uni2/ttl_window/plots"
  "fyp/results/imc/uni2/flow_stats"
  "fyp/results/imc/uni2/flow_concurrency/plots"

  "fyp/results/mawi/cache_sim/source_seen/plots"
  "fyp/results/mawi/cache_sim/source_seen/capacity/plots"
  "fyp/results/mawi/flow_size/plots"
  "fyp/results/mawi/flow_lifetime/plots"
  "fyp/results/mawi/ttl_window/plots"
  "fyp/results/mawi/flow_stats"
  "fyp/results/mawi/flow_concurrency/plots"

  "fyp/results/synthetic/ndp/connection_matrices"
  "fyp/results/synthetic/ndp/raw_logs"
  "fyp/results/synthetic/ndp/cache_sim/congestion/plots"
  "fyp/results/synthetic/ndp/cache_sim/congestion/capacity/plots"
  "fyp/results/synthetic/ndp/cache_sim/route_changes/plots"
  "fyp/results/synthetic/ndp/cache_sim/route_changes/capacity/plots"
  "fyp/results/synthetic/ndp/cache_sim/source_seen/plots"
  "fyp/results/synthetic/ndp/cache_sim/source_seen/capacity/plots"
  "fyp/results/synthetic/ndp/flow_size/plots"
  "fyp/results/synthetic/ndp/flow_lifetime/plots"
  "fyp/results/synthetic/ndp/ttl_window/plots"
  "fyp/results/synthetic/ndp/flow_stats"
  "fyp/results/synthetic/ndp/flow_concurrency/plots"

  "fyp/results/synthetic/hpcc/connection_matrices"
  "fyp/results/synthetic/hpcc/raw_logs"
  "fyp/results/synthetic/hpcc/cache_sim/congestion/plots"
  "fyp/results/synthetic/hpcc/cache_sim/congestion/capacity/plots"
  "fyp/results/synthetic/hpcc/cache_sim/route_changes/plots"
  "fyp/results/synthetic/hpcc/cache_sim/route_changes/capacity/plots"
  "fyp/results/synthetic/hpcc/cache_sim/source_seen/plots"
  "fyp/results/synthetic/hpcc/cache_sim/source_seen/capacity/plots"
  "fyp/results/synthetic/hpcc/flow_size/plots"
  "fyp/results/synthetic/hpcc/flow_lifetime/plots"
  "fyp/results/synthetic/hpcc/ttl_window/plots"
  "fyp/results/synthetic/hpcc/flow_stats"
  "fyp/results/synthetic/hpcc/flow_concurrency/plots"

  "fyp/results/synthetic/tcp/connection_matrices"
  "fyp/results/synthetic/tcp/raw_logs"
  "fyp/results/synthetic/tcp/cache_sim/congestion/plots"
  "fyp/results/synthetic/tcp/cache_sim/congestion/capacity/plots"
  "fyp/results/synthetic/tcp/cache_sim/route_changes/plots"
  "fyp/results/synthetic/tcp/cache_sim/route_changes/capacity/plots"
  "fyp/results/synthetic/tcp/cache_sim/source_seen/plots"
  "fyp/results/synthetic/tcp/cache_sim/source_seen/capacity/plots"
  "fyp/results/synthetic/tcp/flow_size/plots"
  "fyp/results/synthetic/tcp/flow_lifetime/plots"
  "fyp/results/synthetic/tcp/ttl_window/plots"
  "fyp/results/synthetic/tcp/flow_stats"
  "fyp/results/synthetic/tcp/flow_concurrency/plots"

  "fyp/experiments/logs"
  
  "fyp/experiments/run1/dataset/raw_logs"
  "fyp/experiments/run1/dataset/connection_matrices"
  "fyp/experiments/run1/results/flow_stats"
  "fyp/experiments/run1/results/flow_size/plots"
  "fyp/experiments/run1/results/flow_concurrency/plots"
  "fyp/experiments/run1/results/cache_sim/route_changes"
  "fyp/experiments/run1/results/cache_sim/source_seen"
  "fyp/experiments/run1/results/cache_sim/congestion"

  "fyp/experiments/run2/dataset/raw_logs"
  "fyp/experiments/run2/dataset/connection_matrices"
  "fyp/experiments/run2/results/flow_stats"
  "fyp/experiments/run2/results/flow_size/plots"
  "fyp/experiments/run2/results/flow_concurrency/plots"
  "fyp/experiments/run2/results/cache_sim/route_changes"
  "fyp/experiments/run2/results/cache_sim/source_seen"
  "fyp/experiments/run2/results/cache_sim/congestion"

  "fyp/experiments/run3/dataset/raw_logs"
  "fyp/experiments/run3/dataset/connection_matrices"
  "fyp/experiments/run3/results/flow_stats"
  "fyp/experiments/run3/results/flow_size/plots"
  "fyp/experiments/run3/results/flow_concurrency/plots"
  "fyp/experiments/run3/results/cache_sim/route_changes"
  "fyp/experiments/run3/results/cache_sim/source_seen"
  "fyp/experiments/run3/results/cache_sim/congestion"

  "fyp/experiments/run4/dataset/raw_logs"
  "fyp/experiments/run4/dataset/connection_matrices"
  "fyp/experiments/run4/results/flow_stats"
  "fyp/experiments/run4/results/flow_size/plots"
  "fyp/experiments/run4/results/flow_concurrency/plots"
  "fyp/experiments/run4/results/cache_sim/route_changes"
  "fyp/experiments/run4/results/cache_sim/source_seen"
  "fyp/experiments/run4/results/cache_sim/congestion"

  "fyp/experiments/run5/dataset/raw_logs"
  "fyp/experiments/run5/dataset/connection_matrices"
  "fyp/experiments/run5/results/flow_stats"
  "fyp/experiments/run5/results/flow_size/plots"
  "fyp/experiments/run5/results/flow_concurrency/plots"
  "fyp/experiments/run5/results/cache_sim/route_changes"
  "fyp/experiments/run5/results/cache_sim/source_seen"
  "fyp/experiments/run5/results/cache_sim/congestion"

  "fyp/experiments/findings/1_flow_size_sweep"
  "fyp/experiments/findings/2_burst_sweep"
  "fyp/experiments/findings/3_skew_sweep"
  "fyp/experiments/findings/4_source_seen_vs_route_change"
  "fyp/experiments/findings/5_failure_mode_baselines"
  "fyp/experiments/findings/6_concurrent_flow_threshold"
  "fyp/experiments/findings/7_congestion_incast_vs_a2a"
  "fyp/experiments/findings/8_policy_ranking"
)

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[dry-run] would create:"
  printf '  %s\n' "${DIRS[@]}"
  echo "  fyp/experiments/experiments.txt (file)"
else
  mkdir -p "${DIRS[@]}"
  touch "$REPO_ROOT/fyp/experiments/experiments.txt"
  echo "Created directory tree under: $REPO_ROOT"
fi

cat <<'EOF'

Place real datasets here:

1) IMC
   - Uni1 pcaps/text input: fyp/dataset/imc/uni1/uni1_trace_pcap/
   - Uni2 pcaps/text input: fyp/dataset/imc/uni2/uni2_trace_pcap/

2) MAWI
   - Raw dump: fyp/dataset/mawi/200803180000.dump
   - Optional pre-converted text dump: fyp/dataset/mawi/200803180000.dump.txt

3) Synthetic
   - No external dataset needed.
   - Generate logs with: bash fyp/scripts/run_htsim_synthetic.sh --protocol ndp
   - Or for HPCC:  bash fyp/scripts/run_htsim_synthetic.sh --protocol hpcc
   - Or for TCP:   bash fyp/scripts/run_htsim_synthetic.sh --protocol tcp

After placing data, run pipelines from the repository root:
  python3 fyp/scripts/run_imc_pipeline.py uni1
  python3 fyp/scripts/run_imc_pipeline.py uni2
  python3 fyp/scripts/run_mawi_pipeline.py
EOF
