# Project Pipelines (IMC, MAWI, Synthetic)

This guide reflects the current layout:

- IMC data root: `fyp/dataset/imc`
- MAWI data root: `fyp/dataset/mawi`
- Synthetic logs: `fyp/dataset/synthetic/{ndp,hpcc,tcp}`
- Results root: `fyp/results`
- Experiment findings: `fyp/experiments/findings`

All plotting/cache outputs are written under `fyp/results/...`.

## 0. Workspace Setup

Create the expected dataset/results directory tree first:

```bash
bash fyp/scripts/setup_workspace.sh
```

Then place real datasets in:

- IMC Uni1 traces: `fyp/dataset/imc/uni1/uni1_trace_pcap/`
- IMC Uni2 traces: `fyp/dataset/imc/uni2/uni2_trace_pcap/`
- MAWI raw dump: `fyp/dataset/mawi/200803180000.dump`
- Optional MAWI text dump: `fyp/dataset/mawi/200803180000.dump.txt`

Synthetic logs are generated locally (see Section 3).

## 1. IMC Pipeline

### 1.1 Expected Input Layout

- `fyp/dataset/imc/uni1/uni1_trace_pcap/`
- `fyp/dataset/imc/uni2/uni2_trace_pcap/`

### 1.2 Build Top-8 /16 Sink Splits

```bash
python3 fyp/scripts/run_imc_pipeline.py uni1
python3 fyp/scripts/run_imc_pipeline.py uni2
```

This creates:

- `fyp/dataset/imc/uni1/uni1_sinks_top8_prefix16/*.txt`
- `fyp/dataset/imc/uni2/uni2_sinks_top8_prefix16/*.txt`

Sink files are rewritten to HTSIM INT-style log format (not tabular packet rows).
The intermediate conversion directory `<dataset>_trace_txt` is removed automatically
after pipeline completion unless `--keep-txt-dir` is passed.

Naming is dataset-prefixed, for example:

- `uni1_sink_41.177.0.0_16.txt`

### 1.3 Cache Simulation

```bash
bash fyp/scripts/run_cache_sim_imc.sh
# Optional: cap per-split packet count (default: 7,000,000)
IMC_MAX_PACKETS_PER_SPLIT=7000000 bash fyp/scripts/run_cache_sim_imc.sh
```

Outputs:

- `fyp/results/imc/uni1/cache_sim/source_seen/results_uni1_source_seen_top8.csv`
- `fyp/results/imc/uni2/cache_sim/source_seen/results_uni2_source_seen_top8.csv`
- `fyp/results/imc/uni1/cache_sim/source_seen/capacity/results_uni1_source_seen_top8_capacity.csv`
- `fyp/results/imc/uni2/cache_sim/source_seen/capacity/results_uni2_source_seen_top8_capacity.csv`
- `fyp/results/imc/uni1/cache_sim/source_seen/capacity/plots/uni1/`
- `fyp/results/imc/uni2/cache_sim/source_seen/capacity/plots/uni2/`
- Per-sink split CSVs in corresponding `..._splits/` directories

### 1.4 Plots and Stats

#### 1.4.1 Cache Performance
```bash
bash fyp/scripts/run_plot_cache_imc.sh
bash fyp/scripts/run_plot_cache_imc.sh --scale-to-infinite
bash fyp/scripts/run_plot_cache_imc.sh --scale-to-infinite --scale-factor 1.4
bash fyp/scripts/run_plot_cache_imc.sh --switch-budget 512 --hide-redundant-pairs
```

Outputs:

- `fyp/results/imc/uni1/cache_sim/source_seen/plots/`
- `fyp/results/imc/uni2/cache_sim/source_seen/plots/`

#### 1.4.2 Flow Stats Summary
```bash
bash fyp/scripts/run_flow_stats_imc.sh
```

Outputs:

- `fyp/results/imc/uni1/flow_stats/`
- `fyp/results/imc/uni2/flow_stats/`

#### 1.4.3 Flow Size Distribution
```bash
bash fyp/scripts/run_plot_flow_distribution_imc.sh
```

Outputs:

- `fyp/results/imc/uni1/flow_size/plots/`
- `fyp/results/imc/uni2/flow_size/plots/`

#### 1.4.4 Flow Lifetime Distribution
```bash
bash fyp/scripts/run_plot_flow_lifetime_imc_top8.sh
```

Outputs:

- `fyp/results/imc/uni1/flow_lifetime/plots/`
- `fyp/results/imc/uni2/flow_lifetime/plots/`

#### 1.4.5 Flow Temporal Locality
```bash
bash fyp/scripts/run_plot_flow_concurrency_imc_top8.sh
```

Outputs:

- `fyp/results/imc/uni1/flow_concurrency/plots/`
- `fyp/results/imc/uni2/flow_concurrency/plots/`

#### 1.4.6 Inter-Record TTL Window Distribution
```bash
bash fyp/scripts/run_plot_ttl_window_imc_top8.sh
```

Outputs:

- `fyp/results/imc/uni1/ttl_window/plots/`
- `fyp/results/imc/uni2/ttl_window/plots/`

## 2. MAWI Pipeline

### 2.1 Input

- Raw dump (kept): `fyp/dataset/mawi/200803180000.dump`
- Text dump (kept): `fyp/dataset/mawi/200803180000.dump.txt`

### 2.2 Build MAWI Top-8 /16 Sink Splits

```bash
python3 fyp/scripts/run_mawi_pipeline.py
```

Outputs:

- `fyp/dataset/mawi/mawi_sinks_top8_prefix16/*.txt`

MAWI sink files are rewritten to HTSIM INT-style log format after splitting.

### 2.3 Cache Simulation

```bash
bash fyp/scripts/run_cache_sim_mawi.sh
```

Outputs:

- `fyp/results/mawi/cache_sim/source_seen/results_mawi_source_seen_top8.csv`
- `fyp/results/mawi/cache_sim/source_seen/capacity/results_mawi_source_seen_top8_capacity.csv`
- `fyp/results/mawi/cache_sim/source_seen/capacity/plots/mawi/`

### 2.4 Plots and Stats

#### 2.4.1 Cache Performance
```bash
bash fyp/scripts/run_plot_cache_mawi.sh
bash fyp/scripts/run_plot_cache_mawi.sh --scale-to-infinite
bash fyp/scripts/run_plot_cache_mawi.sh --switch-budget 512 --hide-redundant-pairs
```

Outputs:

- `fyp/results/mawi/cache_sim/source_seen/plots/`

#### 2.4.2 Flow Stats Summary
```bash
bash fyp/scripts/run_flow_stats_mawi.sh
```

Outputs:

- `fyp/results/mawi/flow_stats/`

#### 2.4.3 Flow Size Distribution
```bash
bash fyp/scripts/run_plot_flow_distribution_mawi.sh
```

Outputs:

- `fyp/results/mawi/flow_size/plots/`

#### 2.4.4 Flow Lifetime Distribution
```bash
bash fyp/scripts/run_plot_flow_lifetime_mawi_top8.sh
```

Outputs:

- `fyp/results/mawi/flow_lifetime/plots/`

#### 2.4.5 Flow Temporal Locality
```bash
bash fyp/scripts/run_plot_flow_concurrency_mawi_top8.sh
```

Outputs:

- `fyp/results/mawi/flow_concurrency/plots/`

#### 2.4.6 Inter-Record TTL Window Distribution
```bash
bash fyp/scripts/run_plot_ttl_window_mawi_top8.sh
```

Outputs:

- `fyp/results/mawi/ttl_window/plots/`

## 3. Synthetic Pipeline

### 3.1 Dataset Families

Base datasets (one simulation run per dataset):

- `incast_mono`, `a2a_mono`
- `incast_bimodal`, `a2a_bimodal`
- `incast_pareto`, `a2a_pareto`
- `incast_heavytail`, `a2a_heavytail`
- `incast_exponential_skewed`, `a2a_exponential_skewed`

Sweep datasets (multiple values per family):

- `(incast|a2a)_mono_<N>` — flow-size sweep, N in {1,2,4,...,4096} packets
- `(incast|a2a)_heavytail_burst_<N>` — path burstiness sweep, N in {8,16,32,64,128,256} (NDP only)
- `(incast|a2a)_heavytail_sigma_<S>` — flow-size concentration sweep, S tokenized (e.g. `1p0`, `1p5`, `2p0`)
- `(incast|a2a)_heavytail_temp_<N>` — temporal locality sweep, N in {1,2,4,8}
- `(incast|a2a)_pareto_alpha_<A>` — Pareto skew sweep, A tokenized (e.g. `1p0`, `1p5`, `2p0`)

All three protocols (ndp, hpcc, tcp) are supported unless noted otherwise.

### 3.2 Generate Synthetic Datasets

Run all datasets for a protocol:

```bash
bash fyp/scripts/run_htsim_synthetic.sh --protocol ndp
bash fyp/scripts/run_htsim_synthetic.sh --protocol hpcc
bash fyp/scripts/run_htsim_synthetic.sh --protocol tcp
```

Run one dataset or sweep family only:

```bash
bash fyp/scripts/run_htsim_synthetic.sh --protocol ndp --dataset incast_heavytail
bash fyp/scripts/run_htsim_synthetic.sh --protocol ndp --dataset incast_heavytail_burst_n
bash fyp/scripts/run_htsim_synthetic.sh --protocol ndp --dataset incast_heavytail_sigma_n
bash fyp/scripts/run_htsim_synthetic.sh --protocol ndp --dataset incast_mono_n
```

Useful environment variable overrides:

```bash
# Override burst sweep values (NDP only; default: 8,16,32,64,128,256)
BURST_SWEEP_VALUES=8,64,256 bash fyp/scripts/run_htsim_synthetic.sh --protocol ndp

# Override sigma sweep values (default: 0p5,1p0,1p5,2p0,2p5,3p0)
HEAVYTAIL_SIGMA_SWEEP_VALUES=1p0,2p0,3p0 bash fyp/scripts/run_htsim_synthetic.sh --protocol ndp

# Fix random seed
bash fyp/scripts/run_htsim_synthetic.sh --protocol ndp --seed 42
```

Synthetic logs are written to:

- `fyp/dataset/synthetic/ndp/log_*.txt`
- `fyp/dataset/synthetic/hpcc/log_*.txt`
- `fyp/dataset/synthetic/tcp/log_*.txt`

### 3.3 Cache Simulation

Route-change context:

```bash
bash fyp/scripts/run_cache_sim_synthetic.sh --protocol ndp
bash fyp/scripts/run_cache_sim_synthetic.sh --protocol hpcc
bash fyp/scripts/run_cache_sim_synthetic.sh --protocol tcp
# Single dataset or family:
bash fyp/scripts/run_cache_sim_synthetic.sh --protocol ndp --dataset incast_heavytail
bash fyp/scripts/run_cache_sim_synthetic.sh --protocol ndp --dataset incast_heavytail_sigma_n
```

Source-seen context:

```bash
bash fyp/scripts/run_cache_sim_source_seen_synthetic.sh --protocol ndp
bash fyp/scripts/run_cache_sim_source_seen_synthetic.sh --protocol hpcc
```

Congestion context:

```bash
bash fyp/scripts/run_cache_sim_congestion_synthetic.sh --protocol ndp
bash fyp/scripts/run_cache_sim_congestion_synthetic.sh --protocol ndp --range-threshold 8192 --key-level switch
```

Add `--capacity-plots` to any of the above to also generate per-dataset capacity sweep CSVs and plots.

Outputs:

- `fyp/results/synthetic/<protocol>/cache_sim/route_changes/results_synthetic_*.csv`
- `fyp/results/synthetic/<protocol>/cache_sim/source_seen/results_synthetic_source_seen_*.csv`
- `fyp/results/synthetic/<protocol>/cache_sim/congestion/results_synthetic_congestion_*.csv`
- `fyp/results/synthetic/<protocol>/cache_sim/{route_changes,source_seen,congestion}/capacity/` (with `--capacity-plots`)

### 3.4 Plots and Stats

#### 3.4.1 Cache Performance
```bash
bash fyp/scripts/run_plot_cache_synthetic.sh --protocol ndp
bash fyp/scripts/run_plot_cache_synthetic.sh --protocol ndp --mode source_seen
bash fyp/scripts/run_plot_cache_synthetic.sh --protocol ndp --mode congestion --key-level switch
bash fyp/scripts/run_plot_cache_synthetic.sh --protocol ndp --scale-to-infinite
bash fyp/scripts/run_plot_cache_synthetic.sh --protocol ndp --switch-budget 512 --hide-redundant-pairs
# Single dataset:
bash fyp/scripts/run_plot_cache_synthetic.sh --protocol ndp --dataset incast_heavytail
```

Batch plot across all protocols and modes:

```bash
bash fyp/scripts/run_plot_cache_batch.sh
bash fyp/scripts/run_plot_cache_batch.sh --hide-redundant-pairs --switch-budget 512
```

Outputs:

- `fyp/results/synthetic/<protocol>/cache_sim/{route_changes,source_seen,congestion}/plots/`

#### 3.4.2 Flow Stats Summary
```bash
bash fyp/scripts/run_flow_stats_synthetic.sh --protocol ndp
bash fyp/scripts/run_flow_stats_synthetic.sh --protocol hpcc
bash fyp/scripts/run_flow_stats_synthetic.sh --protocol tcp
```

Outputs:

- `fyp/results/synthetic/<protocol>/flow_stats/`

#### 3.4.3 Flow Size Distribution
```bash
bash fyp/scripts/run_plot_flow_distribution_synthetic.sh --protocol ndp
bash fyp/scripts/run_plot_flow_distribution_synthetic.sh --protocol hpcc
```

Outputs:

- `fyp/results/synthetic/<protocol>/flow_size/plots/`

#### 3.4.4 Flow Lifetime Distribution
```bash
bash fyp/scripts/run_plot_flow_lifetime_synthetic.sh --protocol ndp
bash fyp/scripts/run_plot_flow_lifetime_synthetic.sh --protocol hpcc
```

Outputs:

- `fyp/results/synthetic/<protocol>/flow_lifetime/plots/`

#### 3.4.5 Flow Temporal Locality
```bash
bash fyp/scripts/run_plot_flow_concurrency_synthetic.sh --protocol ndp
bash fyp/scripts/run_plot_flow_concurrency_synthetic.sh --protocol hpcc
```

Outputs:

- `fyp/results/synthetic/<protocol>/flow_concurrency/plots/`

#### 3.4.6 Inter-Record TTL Window Distribution
```bash
bash fyp/scripts/run_plot_ttl_window_synthetic.sh --protocol ndp
bash fyp/scripts/run_plot_ttl_window_synthetic.sh --protocol ndp --key-level source
bash fyp/scripts/run_plot_ttl_window_synthetic.sh --protocol ndp --dataset incast_heavytail
```

Outputs:

- `fyp/results/synthetic/<protocol>/ttl_window/plots/`

## 4. Experiment Suite

The experiment suite runs each entry in `fyp/experiments/experiments.txt` across five seeds, then aggregates results into `fyp/experiments/findings/`.

### 4.1 Configure Experiments

Experiments are declared in `fyp/experiments/experiments.txt`. Each non-comment line has three fields:

```
protocol  dataset  context
```

Where `context` is one of `route_changes`, `source_seen`, or `congestion`. Dataset shorthands ending in `_n` expand to the full sweep family (e.g. `incast_heavytail_sigma_n` runs all sigma values).

### 4.2 Run Experiments

Sequential mode (one entry at a time, 5 seeds each):

```bash
bash fyp/scripts/run_experiments.sh
```

Parallel mode (up to 8 concurrent leaf jobs by default):

```bash
bash fyp/scripts/run_experiments.sh --parallel
bash fyp/scripts/run_experiments.sh --parallel --jobs 4
```

Run a single entry by 1-based index:

```bash
bash fyp/scripts/run_experiments.sh --entry 1
bash fyp/scripts/run_experiments.sh --parallel --entry 3
```

Each entry runs the full pipeline for each seed: htsim → flow stats → cache sim → temporal locality plot → flow distribution plot. After all 5 seeds complete, results are aggregated into `fyp/experiments/findings/<subdir>/`.

Aggregate CSVs contain per-policy mean and 95% CI across seeds and are named `mean_ci95_<protocol>_<dataset>.csv`.

### 4.3 Plan Parallel Execution

To see how experiments are grouped into conflict-free parallel waves (entries sharing a protocol and dataset family cannot run concurrently):

```bash
python3 fyp/scripts/schedule_experiments.py
# Print the actual bash commands for each wave:
python3 fyp/scripts/schedule_experiments.py --commands
```

### 4.4 Aggregate Results Manually

To re-aggregate specific result CSVs from already-completed seed runs without rerunning:

```bash
python3 fyp/scripts/aggregate_runs.py \
  --inputs fyp/experiments/run{1,2,3,4,5}/results/cache_sim/route_changes/ndp/results_synthetic_incast_heavytail.csv \
  --output fyp/experiments/findings/8_policy_ranking/mean_ci95_ndp_incast_heavytail.csv
```

### 4.5 Plot Findings

After findings are populated, generate summary plots from the aggregated CSVs:

```bash
python3 fyp/scripts/plot_chapter5_figures.py
```

Outputs:

- `fyp/report/img/obs1_skew_sweep.png` — suppression vs sigma sweep (oracle / LRU / best, with 95% CI)
- `fyp/report/img/obs2_burst_sweep.png` — suppression vs burst sweep (oracle / LRU / best, with 95% CI)
- `fyp/report/img/obs8_policy_ranking.png` — mean forward efficiency vs capacity (all policies)

Required findings directories:

- `fyp/experiments/findings/3_skew_sweep/`
- `fyp/experiments/findings/2_burst_sweep/`
- `fyp/experiments/findings/8_policy_ranking/`

## 5. Notes

- IMC/MAWI sink readers consume `.txt` split files; IMC wrappers also tolerate legacy `.log` split files.
- Cache plot scripts can draw toggleable vertical cache-capacity markers:
  - max concurrent flows (`--max-concurrency N`, `--no-max-concurrency`)
  - total unique flows (`--unique-flows N`, `--no-unique-flows`)
  - congestion mode: peak and unique congested keys (inferred from `--qs-threshold` and `--key-level`; disable via `--no-congestion-markers`)
  - practical switch budget (`--switch-budget N`)
- To enable automatic max-concurrency and unique-flow markers, run flow-stats first so summaries exist.
- Policy visibility can be toggled at plot time without re-running simulation:
  - hide one or more policies: `--disable-policy POLICY` (repeatable)
  - keep only selected policies: `--include-policy POLICY` (repeatable)
  - hide near-duplicate defaults: `--hide-redundant-pairs`
- For IMC/MAWI split plots, marker inference is split-specific (each split CSV tries to read its matching `*_flow_stats.txt`; the total CSV uses `*_all_flow_stats.txt`).
- NDP is the primary protocol for route-change and source-seen evaluations. HPCC/TCP route-change results often show lower path churn due to ECMP per-flow routing; use NDP for route-change-centric analysis.
- HPCC burst sweep datasets are not meaningful (ECMP routing is stable by design); use NDP burst sweep for path-stability evaluation.
