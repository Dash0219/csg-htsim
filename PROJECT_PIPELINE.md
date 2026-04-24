# DASH Dataset Pipelines (IMC, MAWI, Synthetic)

This guide reflects the current layout:

- IMC data root: `fyp/dash_dataset/imc`
- MAWI data root: `fyp/dash_dataset/mawi`
- Synthetic logs: `fyp/dash_dataset/synthetic/{ndp,hpcc}`
- Results root: `dash_results`

All plotting/cache outputs are written under `fyp/dash_results/...`.

## 0. Workspace Setup

Create the expected dataset/results directory tree first:

```bash
bash fyp/dash_scripts/setup_dash_workspace.sh
```

Then place real datasets in:

- IMC Univ1 traces: `fyp/dash_dataset/imc/univ1/univ1_trace_pcap/`
- IMC Univ2 traces: `fyp/dash_dataset/imc/univ2/univ2_trace_pcap/`
- MAWI raw dump: `fyp/dash_dataset/mawi/200803180000.dump`
- Optional MAWI text dump: `fyp/dash_dataset/mawi/200803180000.dump.txt`

Synthetic logs are generated locally (no external input needed):

```bash
cd sim/datacenter
bash fyp/dash_scripts/run_htsim_synthetic.sh --protocol ndp
bash fyp/dash_scripts/run_htsim_synthetic.sh --protocol hpcc
# Sweep-family shorthands (one topology at a time)
bash fyp/dash_scripts/run_htsim_synthetic.sh --protocol ndp --dataset a2a_mono_n
bash fyp/dash_scripts/run_htsim_synthetic.sh --protocol ndp --dataset a2a_mono_burst_n
bash fyp/dash_scripts/run_htsim_synthetic.sh --protocol ndp --dataset a2a_pareto_alpha_n
bash fyp/dash_scripts/run_htsim_synthetic.sh --protocol ndp --dataset a2a_pareto_temp_n
```

## 1. IMC Pipeline

### 1.1 Expected Input Layout

- `fyp/dash_dataset/imc/univ1/univ1_trace_pcap/`
- `fyp/dash_dataset/imc/univ2/univ2_trace_pcap/`

### 1.2 Build Top-8 /16 Sink Splits

```bash
python3 fyp/dash_scripts/run_imc_pipeline.py univ1
python3 fyp/dash_scripts/run_imc_pipeline.py univ2
```

This creates:

- `fyp/dash_dataset/imc/univ1/univ1_sinks_top8_prefix16/*.txt`
- `fyp/dash_dataset/imc/univ2/univ2_sinks_top8_prefix16/*.txt`

Sink files are rewritten to HTSIM INT-style log format (not tabular packet rows).
The intermediate conversion directory `<dataset>_trace_txt` is removed automatically
after pipeline completion unless `--keep-txt-dir` is passed.

Naming is dataset-prefixed, for example:

- `univ1_sink_41.177.0.0_16.txt`

### 1.3 Cache Simulation

```bash
bash fyp/dash_scripts/run_cache_sim_imc.sh
# Optional: cap per-split packet count (default: 7,000,000)
IMC_MAX_PACKETS_PER_SPLIT=7000000 bash fyp/dash_scripts/run_cache_sim_imc.sh
```

The runner now streams progress to the terminal and writes the same output to run logs.

Outputs:

- `fyp/dash_results/imc/univ1/cache_sim/source_seen/results_univ1_source_seen_top8.csv`
- `fyp/dash_results/imc/univ2/cache_sim/source_seen/results_univ2_source_seen_top8.csv`
- `fyp/dash_results/imc/univ1/cache_sim/source_seen/capacity/results_univ1_source_seen_top8_capacity.csv`
- `fyp/dash_results/imc/univ2/cache_sim/source_seen/capacity/results_univ2_source_seen_top8_capacity.csv`
- `fyp/dash_results/imc/univ1/cache_sim/source_seen/capacity/plots/univ1/`
- `fyp/dash_results/imc/univ2/cache_sim/source_seen/capacity/plots/univ2/`
- `fyp/dash_results/imc/univ1/cache_sim/source_seen/run_univ1_source_seen_top8.out`
- `fyp/dash_results/imc/univ2/cache_sim/source_seen/run_univ2_source_seen_top8.out`
- Per-sink split CSVs in corresponding `..._splits/` directories

### 1.4 Plots and Stats

#### 1.4.1 Cache Performance
```bash
bash fyp/dash_scripts/run_plot_cache_imc.sh
bash fyp/dash_scripts/run_plot_cache_imc.sh --scale-to-infinite
bash fyp/dash_scripts/run_plot_cache_imc.sh --scale-to-infinite --scale-factor 1.4
bash fyp/dash_scripts/run_plot_cache_imc.sh --switch-budget 512 --hide-redundant-pairs
```

Outputs:

- `fyp/dash_results/imc/univ1/cache_sim/source_seen/plots/`
- `fyp/dash_results/imc/univ2/cache_sim/source_seen/plots/`

#### 1.4.2 Flow Stats Summary
```bash
bash fyp/dash_scripts/run_flow_stats_imc.sh
```

Outputs:

- `fyp/dash_results/imc/univ1/flow_stats/`
- `fyp/dash_results/imc/univ2/flow_stats/`

#### 1.4.3 Flow Size Distribution
```bash
bash fyp/dash_scripts/run_plot_flow_distribution_imc.sh
```

Outputs:

- `fyp/dash_results/imc/univ1/flow_size/plots/`
- `fyp/dash_results/imc/univ2/flow_size/plots/`

#### 1.4.4 Flow Lifetime Distribution
```bash
bash fyp/dash_scripts/run_plot_flow_lifetime_imc_top8.sh
```

Outputs:

- `fyp/dash_results/imc/univ1/flow_lifetime/plots/`
- `fyp/dash_results/imc/univ2/flow_lifetime/plots/`

#### 1.4.5 Flow Temporal Locality
```bash
bash fyp/dash_scripts/run_plot_temporal_locality_imc_top8.sh
```

Outputs:

- `fyp/dash_results/imc/univ1/temporal_locality/plots/`
- `fyp/dash_results/imc/univ2/temporal_locality/plots/`

## 2. MAWI Pipeline

### 2.1 Input

- Raw dump (kept): `fyp/dash_dataset/mawi/200803180000.dump`
- Text dump (kept): `fyp/dash_dataset/mawi/200803180000.dump.txt`

### 2.2 Build MAWI Top-8 /16 Sink Splits

```bash
python3 fyp/dash_scripts/run_mawi_pipeline.py
```

Outputs:

- `fyp/dash_dataset/mawi/mawi_sinks_top8_prefix16/*.txt`

MAWI sink files are rewritten to HTSIM INT-style log format after splitting.

### 2.3 Cache Simulation

```bash
bash fyp/dash_scripts/run_cache_sim_mawi.sh
```

Outputs:

- `fyp/dash_results/mawi/cache_sim/source_seen/`
- `fyp/dash_results/mawi/cache_sim/source_seen/capacity/results_mawi_source_seen_top8_capacity.csv`
- `fyp/dash_results/mawi/cache_sim/source_seen/capacity/plots/mawi/`

### 2.4 Plots and Stats

#### 2.4.1 Cache Performance
```bash
bash fyp/dash_scripts/run_plot_cache_mawi.sh
bash fyp/dash_scripts/run_plot_cache_mawi.sh --scale-to-infinite
bash fyp/dash_scripts/run_plot_cache_mawi.sh --switch-budget 512 --hide-redundant-pairs
```

Outputs:

- `fyp/dash_results/mawi/cache_sim/source_seen/plots/`

#### 2.4.2 Flow Stats Summary
```bash
bash fyp/dash_scripts/run_flow_stats_mawi.sh
```

Outputs:

- `fyp/dash_results/mawi/flow_stats/`

#### 2.4.3 Flow Size Distribution
```bash
bash fyp/dash_scripts/run_plot_flow_distribution_mawi.sh
```

Outputs:

- `fyp/dash_results/mawi/flow_size/plots/`

#### 2.4.4 Flow Lifetime Distribution
```bash
bash fyp/dash_scripts/run_plot_flow_lifetime_mawi_top8.sh
```

Outputs:

- `fyp/dash_results/mawi/flow_lifetime/plots/`

#### 2.4.5 Flow Temporal Locality
```bash
bash fyp/dash_scripts/run_plot_temporal_locality_mawi_top8.sh
```

Outputs:

- `fyp/dash_results/mawi/temporal_locality/plots/`

## 3. Synthetic Pipeline

Synthetic dataset suite is now scoped to two parts only.

Part 1 (proof-of-concept):

- `incast_mono`, `a2a_mono`
- `incast_bimodal`, `a2a_bimodal`
- `incast_pareto`, `a2a_pareto`
- `incast_exponential_skewed`, `a2a_exponential_skewed`

Part 2 (sweeps):

- `incast_mono_burst_<N>`, `a2a_mono_burst_<N>` where `N in {8,16,32,64,128,256}` and flow size is fixed to 256 packets
- `incast_pareto_alpha_<A>`, `a2a_pareto_alpha_<A>` where `<A>` is an alpha token (`1p0`, `1p5`, ...)
- `incast_pareto_temp_<N>`, `a2a_pareto_temp_<N>` where `N in {1,2,4,8}`
- `incast_mono_<N>`, `a2a_mono_<N>` where `N in {1,2,4,...,4096}` packet counts


### 3.1 Generate Synthetic Datasets

```bash
bash fyp/dash_scripts/run_htsim_synthetic.sh --protocol ndp
bash fyp/dash_scripts/run_htsim_synthetic.sh --protocol hpcc
# Example: run one skew dataset only
bash fyp/dash_scripts/run_htsim_synthetic.sh --protocol ndp --dataset a2a_pareto_alpha_1p0
# Example: explicit alpha sweep values (x_m is fixed by PARETO_SKEW_BASE_XM, default 1)
PARETO_ALPHA_SWEEP_VALUES=1.0,1.5,2.0,2.5,3.0,3.5 \
  bash fyp/dash_scripts/run_htsim_synthetic.sh --protocol ndp
```

Synthetic protocol-specific logs are written to:

- `fyp/dash_dataset/synthetic/ndp/log_*.txt`
- `fyp/dash_dataset/synthetic/hpcc/log_*.txt`

### 3.2 Cache Simulation

```bash
bash fyp/dash_scripts/run_cache_sim_synthetic.sh --protocol ndp
bash fyp/dash_scripts/run_cache_sim_synthetic.sh --protocol hpcc
bash fyp/dash_scripts/run_cache_sim_synthetic.sh --protocol ndp --dataset a2a_pareto_alpha_1p0

bash fyp/dash_scripts/run_cache_sim_source_seen_synthetic.sh --protocol ndp
bash fyp/dash_scripts/run_cache_sim_source_seen_synthetic.sh --protocol hpcc

bash fyp/dash_scripts/run_cache_sim_congestion_synthetic.sh --protocol hpcc --qs-threshold 50000
```

Outputs:

- `fyp/dash_results/synthetic/{ndp,hpcc}/cache_sim/route_changes/results_synthetic_*.csv`
- `fyp/dash_results/synthetic/{ndp,hpcc}/cache_sim/source_seen/results_synthetic_source_seen_*.csv`
- `fyp/dash_results/synthetic/{ndp,hpcc}/cache_sim/{route_changes,source_seen,congestion}/capacity/results_*_capacity.csv`
- `fyp/dash_results/synthetic/{ndp,hpcc}/cache_sim/{route_changes,source_seen,congestion}/capacity/plots/<dataset>/`

### 3.3 Plots and Stats

#### 3.3.1 Cache Performance
```bash
bash fyp/dash_scripts/run_plot_cache_synthetic.sh --protocol ndp
bash fyp/dash_scripts/run_plot_cache_synthetic.sh --protocol hpcc --scale-to-infinite
bash fyp/dash_scripts/run_plot_cache_synthetic.sh --protocol hpcc --mode source_seen --scale-to-infinite --scale-factor 1.4
bash fyp/dash_scripts/run_plot_cache_synthetic.sh --protocol hpcc --mode congestion --qs-threshold 50000 --key-level switch
```

Outputs:

- `fyp/dash_results/synthetic/{ndp,hpcc}/cache_sim/{route_changes,source_seen,congestion}/plots/`

#### 3.3.2 Flow Stats Summary
```bash
bash fyp/dash_scripts/run_flow_stats_synthetic.sh --protocol ndp
bash fyp/dash_scripts/run_flow_stats_synthetic.sh --protocol hpcc
```

Outputs:

- `fyp/dash_results/synthetic/{ndp,hpcc}/flow_stats/`

#### 3.3.3 Flow Size Distribution
```bash
bash fyp/dash_scripts/run_plot_flow_distribution_synthetic.sh --protocol ndp
bash fyp/dash_scripts/run_plot_flow_distribution_synthetic.sh --protocol hpcc
```

Outputs:

- `fyp/dash_results/synthetic/{ndp,hpcc}/flow_size/plots/`

#### 3.3.4 Flow Lifetime Distribution
```bash
bash fyp/dash_scripts/run_plot_flow_lifetime_synthetic.sh --protocol ndp
bash fyp/dash_scripts/run_plot_flow_lifetime_synthetic.sh --protocol hpcc
```

Outputs:

- `fyp/dash_results/synthetic/{ndp,hpcc}/flow_lifetime/plots/`

#### 3.3.5 Flow Temporal Locality
```bash
bash fyp/dash_scripts/run_plot_temporal_locality_synthetic.sh --protocol ndp
bash fyp/dash_scripts/run_plot_temporal_locality_synthetic.sh --protocol hpcc
```

Outputs:

- `fyp/dash_results/synthetic/{ndp,hpcc}/temporal_locality/plots/`

## 4. Experiment Suite

Run all four experiments over synthetic cache CSVs:

```bash
bash fyp/dash_scripts/run_experiments.sh --protocol ndp --topology a2a
bash fyp/dash_scripts/run_experiments.sh --protocol ndp --topology incast
bash fyp/dash_scripts/run_experiments.sh --protocol hpcc --topology a2a
bash fyp/dash_scripts/run_experiments.sh --protocol hpcc --topology incast
```

Useful options:

- `--experiments 1,2,3,4` to select a subset
- `--pareto-alpha-values 1.0,1.5,2.0,2.5,3.0,3.5`
- `--temporal-values 1,2,4,8`
- `--exp34-temporal-all` (default) or `--exp34-temporal-tail`
- `--anchor <topology>_pareto_alpha_1p0` to override the default anchor dataset
- `--no-generate` to fail-fast if any required dataset/CSV is missing

The script is reuse-first:

- It checks whether synthetic logs and cache CSVs already exist.
- It only invokes dataset generation and cache simulation when required artifacts are missing.
- With `--no-generate`, it fails fast instead of regenerating.

Result layout:

- `fyp/dash_results/experiments/exp1_workload_matrix/`
- `fyp/dash_results/experiments/exp2_pressure/`
- `fyp/dash_results/experiments/exp3_admission/`
- `fyp/dash_results/experiments/exp4_ttl_freshness/`

Experiment dataset design summary:

- Exp1 workload matrix axes: `pareto_alpha`, `mono_burst`, `mono_<N>`, and `pareto_temp`
- Exp2 pressure sweep: anchor `pareto_alpha_1p0` + `mono_burst_64` + `mono_256` + temporal tail dataset
- Exp3/Exp4 studies: anchor + `mono_burst_64` + `mono_256` + temporal set(s) selected by `--exp34-temporal-all|--exp34-temporal-tail`

Experiment mapping:

- `1`: Workload matrix (4 axes)
- `2`: Pressure sweep (capacity-pressure breakdown)
- `3`: Admission study (admission-family deltas vs LRU)
- `4`: TTL/freshness study (TTL/freshness failure analysis)

## 5. Cache Design Provenance

Active baseline policies:

- `Infinite`
- `LRU`
- `FIFO`
- `LFU`
- `LRUTTL`

Active admission / freshness policies:

- `OneHitWonderLRU`
- `PendingAdmissionLRU`
- `PITCollapsedLRU`
- `AdaptiveAdmissionLRU`
- `OnlineAdaptiveAdmissionLRU`
- `TimeLimitedBloomLRU`
- `TinyLFULRU`
- `TinyCacheLRU`
- `FreshnessInvalidationLRU`
- `CacheINTFreshnessLRU`
- `FlowLifetimeAdaptiveTTL`

Paper-backed policies:

- `TinyLFULRU` -> [TinyLFU: A Highly Efficient Cache Admission Policy](sim/datacenter/dash_papers/tiny_lfu.pdf)
- `TinyCacheLRU` -> [TinyCache - An Effective Cache Admission Filter](sim/datacenter/dash_papers/tiny_cache.pdf)
- `OneHitWonderLRU` -> [Algorithmic Nuggets in Content Delivery](sim/datacenter/dash_papers/algorithmic_nuggets.pdf)
- `TimeLimitedBloomLRU` -> [Time-limited Bloom Filter](sim/datacenter/dash_papers/time-limited_BF.pdf)
- `CacheINTFreshnessLRU` -> [Cache-INT: A new approach to optimize in-network telemetry](sim/datacenter/dash_papers/cache_int.pdf)

Implemented in this repo without a source paper pinned in `dash_papers`:

- `PITCollapsedLRU` - PIT-inspired inflight collapsing cache
- `PendingAdmissionLRU` - legacy exact second-touch admission baseline
- `AdaptiveAdmissionLRU` - pressure-adaptive admission controller
- `OnlineAdaptiveAdmissionLRU` - multi-mode adaptive admission controller
- `FreshnessInvalidationLRU` - freshness-based invalidation policy
- `FlowLifetimeAdaptiveTTL` - lifetime-aware adaptive freshness window

Archived / no longer surfaced by the default CLIs:

- `VolatilityAwareLRU`
- `SegmentedLRU`
- `TwoFilterOHWLRU`
- `DualFreshnessLRU`
- `OnlineAdaptiveDualTTL`

## 6. Cache Testing

Run from repository root.

Install test dependencies:

```bash
./.venv/bin/python -m pip install -r fyp/dash_tests/requirements.txt
```

Run cache unit tests only:

```bash
./.venv/bin/python -m pytest fyp/dash_tests/test_cache_implementations.py -q
```

Run cache tests with coverage gate (default `COVERAGE_MIN=100`):

```bash
bash fyp/dash_tests/run_cache_tests.sh
```

Override coverage threshold for iterative runs:

```bash
COVERAGE_MIN=80 bash fyp/dash_tests/run_cache_tests.sh
```

## 7. Notes

- IMC/MAWI sink readers consume `.txt` split files; IMC wrappers also tolerate legacy `.log` split files.
- Cache plot scripts can draw toggleable vertical cache-capacity markers for:
	- max concurrent flows (`--max-concurrency N`, `--no-max-concurrency`)
	- total unique flows (`--unique-flows N`, `--no-unique-flows`)
	- congestion mode replacements: peak congested keys and unique congested keys (inferred from `--qs-threshold` and `--key-level`; disable via `--no-congestion-markers`)
	- practical switch budget (`--switch-budget N`)
- To enable automatic max-concurrency and unique-flow markers, run flow-stats first so summaries exist:
	- `bash fyp/dash_scripts/run_flow_stats_imc.sh`
	- `bash fyp/dash_scripts/run_flow_stats_mawi.sh`
	- `bash fyp/dash_scripts/run_flow_stats_synthetic.sh --protocol ndp`
	- `bash fyp/dash_scripts/run_flow_stats_synthetic.sh --protocol hpcc`
- For IMC/MAWI split plots, marker inference is split-specific (each split CSV tries to read its matching
	`*_flow_stats.txt` file, while the total CSV uses `*_all_flow_stats.txt`).
- Policy visibility can be toggled at plot time without re-running simulation:
	- hide one or more policies: `--disable-policy POLICY` (repeatable)
	- keep only selected policies: `--include-policy POLICY` (repeatable)
	- hide near-duplicate defaults: `--hide-redundant-pairs`
- If layout changes again, update wrapper scripts first (`run_*_imc.sh`, `run_*_mawi.sh`) and then refresh this guide.
- HPCC route-change sweeps can under-represent path churn with default `ecmp_host` routing because per-flow paths are often stable; use NDP synthetic runs for route-change-centric evaluation and HPCC runs for queue/congestion-centric evaluation.
