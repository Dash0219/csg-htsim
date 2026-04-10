# DASH Dataset Pipelines (IMC, MAWI, Synthetic)

This guide reflects the current layout:

- IMC data root: `dash_dataset/imc`
- MAWI data root: `dash_dataset/mawi`
- Synthetic logs: `dash_dataset/synthetic`
- Results root: `dash_results`

All plotting/cache outputs are written under `dash_results/...`.

## 0. Workspace Setup

Create the expected dataset/results directory tree first:

```bash
bash sim/datacenter/dash_scripts/setup_dash_workspace.sh
```

Then place real datasets in:

- IMC Univ1 traces: `sim/datacenter/dash_dataset/imc/univ1/univ1_trace_pcap/`
- IMC Univ2 traces: `sim/datacenter/dash_dataset/imc/univ2/univ2_trace_pcap/`
- MAWI raw dump: `sim/datacenter/dash_dataset/mawi/200803180000.dump`
- Optional MAWI text dump: `sim/datacenter/dash_dataset/mawi/200803180000.dump.txt`

Synthetic logs are generated locally (no external input needed):

```bash
cd sim/datacenter
bash dash_scripts/run_htsim_synthetic.sh
```

## 1. IMC Pipeline

### 1.1 Expected Input Layout

- `dash_dataset/imc/univ1/univ1_trace_pcap/`
- `dash_dataset/imc/univ2/univ2_trace_pcap/`

### 1.2 Build Top-8 /16 Sink Splits

```bash
python3 dash_scripts/run_imc_pipeline.py univ1
python3 dash_scripts/run_imc_pipeline.py univ2
```

This creates:

- `dash_dataset/imc/univ1/univ1_sinks_top8_prefix16/*.txt`
- `dash_dataset/imc/univ2/univ2_sinks_top8_prefix16/*.txt`

Sink files are rewritten to HTSIM INT-style log format (not tabular packet rows).
The intermediate conversion directory `<dataset>_trace_txt` is removed automatically
after pipeline completion unless `--keep-txt-dir` is passed.

Naming is dataset-prefixed, for example:

- `univ1_sink_41.177.0.0_16.txt`

### 1.3 Source-Seen Cache Sweep on IMC Top-8

```bash
bash dash_scripts/run_cache_sim_imc.sh
```

Outputs:

- `dash_results/imc/univ1/cache_sim/source_seen/results_univ1_source_seen_top8.csv`
- `dash_results/imc/univ2/cache_sim/source_seen/results_univ2_source_seen_top8.csv`
- Per-sink split CSVs in corresponding `..._splits/` directories

### 1.4 Plot IMC Cache Sweeps

```bash
bash dash_scripts/run_plot_cache_imc.sh
bash dash_scripts/run_plot_cache_imc.sh --scale-to-infinite
bash dash_scripts/run_plot_cache_imc.sh --scale-to-infinite --scale-factor 1.4
bash dash_scripts/run_plot_cache_imc.sh --switch-budget 512 --hide-redundant-pairs
```

Default output:

- `dash_results/imc/univ1/cache_sim/source_seen/plots/`
- `dash_results/imc/univ2/cache_sim/source_seen/plots/`

### 1.5 Flow Stats and Temporal Locality (IMC Top-8)

```bash
bash dash_scripts/run_plot_flow_distribution_imc.sh
bash dash_scripts/run_flow_stats_imc.sh
bash dash_scripts/run_plot_temporal_locality_imc_top8.sh
```

Outputs:

- Flow stats: `dash_results/imc/univ1/flow_stats/`, `dash_results/imc/univ2/flow_stats/`
- Flow distribution plots: `dash_results/imc/univ1/flow_distribution/plots/`, `dash_results/imc/univ2/flow_distribution/plots/`
- Temporal plots: `dash_results/imc/univ1/temporal_locality/plots/`, `dash_results/imc/univ2/temporal_locality/plots/`

## 2. MAWI Pipeline

### 2.1 Input

- Raw dump (kept): `dash_dataset/mawi/200803180000.dump`
- Text dump (kept): `dash_dataset/mawi/200803180000.dump.txt`

### 2.2 Build MAWI Top-8 /16 Sink Splits

```bash
python3 dash_scripts/run_mawi_pipeline.py
```

Outputs:

- `dash_dataset/mawi/mawi_sinks_top8_prefix16/*.txt`

MAWI sink files are rewritten to HTSIM INT-style log format after splitting.

### 2.3 Source-Seen Cache, Flow Stats, Temporal Locality

```bash
bash dash_scripts/run_cache_sim_mawi.sh
bash dash_scripts/run_plot_cache_mawi.sh
bash dash_scripts/run_plot_cache_mawi.sh --scale-to-infinite
bash dash_scripts/run_plot_cache_mawi.sh --switch-budget 512 --hide-redundant-pairs
bash dash_scripts/run_plot_flow_distribution_mawi.sh
bash dash_scripts/run_flow_stats_mawi.sh
bash dash_scripts/run_plot_temporal_locality_mawi_top8.sh
```

Outputs under:

- `dash_results/mawi/cache_sim/source_seen/`
- `dash_results/mawi/flow_distribution/plots/`
- `dash_results/mawi/flow_stats/`
- `dash_results/mawi/temporal_locality/plots/`

## 3. Synthetic Pipeline

Base dataset names are now:

- `incast_mono`
- `a2a_mono`

Low-temp variants follow the same pattern:

- `incast_mono_low_temp_locality`
- `a2a_mono_low_temp_locality`

Other distributions remain unchanged (`*_bimodal`, `*_pareto`, etc.).

### 3.1 Generate Synthetic Logs

```bash
bash dash_scripts/run_htsim_synthetic.sh
bash dash_scripts/run_htsim_synthetic.sh --dataset incast_mono
bash dash_scripts/run_htsim_synthetic.sh --low-temp-locality --dataset a2a_mono
```

### 3.2 Cache Sweeps

```bash
bash dash_scripts/run_cache_sim_synthetic.sh
bash dash_scripts/run_cache_sim_source_seen_synthetic.sh
```

Outputs:

- `dash_results/synthetic/cache_sim/route_changes/results_synthetic_*.csv`
- `dash_results/synthetic/cache_sim/source_seen/results_synthetic_source_seen_*.csv`

Note: synthetic `source_seen` now uses true source-seen semantics (one signature per source),
so when cache capacity exceeds active source count it should approach the infinite baseline.

### 3.3 Plots and Stats

```bash
bash dash_scripts/run_plot_cache_synthetic.sh
bash dash_scripts/run_plot_cache_synthetic.sh --scale-to-infinite
bash dash_scripts/run_plot_cache_synthetic.sh --mode source_seen --scale-to-infinite --scale-factor 1.4
bash dash_scripts/run_plot_cache_synthetic.sh --switch-budget 512 --hide-redundant-pairs
bash dash_scripts/run_plot_flow_distribution_synthetic.sh
bash dash_scripts/run_plot_temporal_locality_synthetic.sh
bash dash_scripts/run_flow_stats_synthetic.sh
```

Default synthetic plot outputs:

- Cache plots: `dash_results/synthetic/cache_sim/{route_changes,source_seen}/plots/`
- Flow distribution: `dash_results/synthetic/flow_distribution/plots/`
- Temporal locality: `dash_results/synthetic/temporal_locality/plots/`
- Flow stats: `dash_results/synthetic/flow_stats/`

## 5. Notes

- Old dataset aliases `incast` and `a2a` are still accepted by script selectors and normalized to `incast_mono` and `a2a_mono`.
- IMC/MAWI sink readers consume `.txt` split files; IMC wrappers also tolerate legacy `.log` split files.
- Cache plot scripts can draw toggleable vertical cache-capacity markers for:
	- max concurrent flows (`--max-concurrency N`, `--no-max-concurrency`)
	- total unique flows (`--unique-flows N`, `--no-unique-flows`)
	- practical switch budget (`--switch-budget N`)
- To enable automatic max-concurrency and unique-flow markers, run flow-stats first so summaries exist:
	- `bash dash_scripts/run_flow_stats_imc.sh`
	- `bash dash_scripts/run_flow_stats_mawi.sh`
	- `bash dash_scripts/run_flow_stats_synthetic.sh`
- For IMC/MAWI split plots, marker inference is split-specific (each split CSV tries to read its matching
	`*_flow_stats.txt` file, while the total CSV uses `*_all_flow_stats.txt`).
- Policy visibility can be toggled at plot time without re-running simulation:
	- hide one or more policies: `--disable-policy POLICY` (repeatable)
	- keep only selected policies: `--include-policy POLICY` (repeatable)
	- hide near-duplicate defaults: `--hide-redundant-pairs`
- If layout changes again, update wrapper scripts first (`run_*_imc.sh`, `run_*_mawi.sh`) and then refresh this guide.
