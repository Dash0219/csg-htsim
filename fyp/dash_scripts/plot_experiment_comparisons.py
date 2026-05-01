#!/usr/bin/env python3
"""Generate cross-dataset comparison plots for thesis experiments.

This script complements plot_cache.py by producing comparison views where datasets
or policy families are contrasted directly instead of plotting one CSV at a time.
"""

import argparse
import csv
import math
import os
import re
from collections import defaultdict

import matplotlib.pyplot as plt


def _read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _dataset_value(ds):
    m = re.search(r"_(\d+)$", ds)
    if m:
        return int(m.group(1))
    return None


def _save(fig, out_dir, name):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"Saved {path}")


def plot_exp1(exp_root, out_dir, flow_stats_csv=None):
    path = os.path.join(exp_root, "flow_concurrency_axis_summary.csv")
    if not os.path.exists(path):
        return
    rows = _read_csv(path)

    curve = []
    for ds in sorted({r["dataset"] for r in rows}, key=lambda x: _dataset_value(x) or 0):
        val = _dataset_value(ds)
        if val is None:
            continue
        lru = [
            r
            for r in rows
            if r["dataset"] == ds and r["cache"] == "LRU" and int(float(r["capacity"])) == 4096
        ]
        inf = [
            r
            for r in rows
            if r["dataset"] == ds and r["cache"] == "Infinite" and int(float(r["capacity"])) == 4096
        ]
        if lru:
            curve.append((val, float(lru[0]["suppression_rate"]), "LRU@4096"))
        if inf:
            curve.append((val, float(inf[0]["suppression_rate"]), "Infinite@4096"))

    if curve:
        by_name = defaultdict(list)
        for x, y, name in curve:
            by_name[name].append((x, y))
        fig, ax = plt.subplots(figsize=(8.5, 4.2))
        for name, pts in by_name.items():
            pts.sort(key=lambda p: p[0])
            ax.plot([p[0] for p in pts], [p[1] for p in pts], marker="o", linewidth=2.2, label=name)
        ax.set_xscale("log", base=2)
        ax.set_xticks(sorted({c[0] for c in curve}))
        ax.set_xlabel("Temporal multiplier N in a2a_pareto_temp_N")
        ax.set_ylabel("Suppression rate")
        ax.set_title("Exp1 temporal sweep: suppression vs temporal multiplier")
        ax.grid(alpha=0.25)
        ax.legend()
        _save(fig, out_dir, "exp1_temporal_multiplier_comparison.png")

    if flow_stats_csv and os.path.exists(flow_stats_csv):
        flow_rows = _read_csv(flow_stats_csv)
        flow_map = {r["dataset"]: int(float(r["max_concurrent_flows"])) for r in flow_rows}
        comp = []
        for ds in sorted(flow_map.keys(), key=lambda x: _dataset_value(x) or 0):
            if "temp_" not in ds:
                continue
            val = _dataset_value(ds)
            if val is None:
                continue
            lru = [
                r
                for r in rows
                if r["dataset"] == ds and r["cache"] == "LRU" and int(float(r["capacity"])) == 4096
            ]
            if not lru:
                continue
            comp.append((val, float(lru[0]["suppression_rate"]), flow_map[ds]))

        if comp:
            comp.sort(key=lambda x: x[0])
            fig, ax1 = plt.subplots(figsize=(8.5, 4.2))
            ax2 = ax1.twinx()
            x = [c[0] for c in comp]
            ax1.plot(x, [c[1] for c in comp], "-o", color="#0f4c81", linewidth=2.2, label="LRU@4096 suppression")
            ax2.plot(x, [c[2] for c in comp], "--s", color="#cf4f00", linewidth=2.0, label="Max concurrent flows")
            ax1.set_xscale("log", base=2)
            ax1.set_xticks(x)
            ax1.set_xlabel("Temporal multiplier N")
            ax1.set_ylabel("Suppression rate")
            ax2.set_ylabel("Max concurrent flows")
            ax1.set_title("Exp1 temporal sweep: suppression vs measured concurrency")
            ax1.grid(alpha=0.25)
            l1, n1 = ax1.get_legend_handles_labels()
            l2, n2 = ax2.get_legend_handles_labels()
            ax1.legend(l1 + l2, n1 + n2, loc="upper right")
            _save(fig, out_dir, "exp1_temporal_vs_concurrency.png")


def plot_exp2(exp_root, out_dir):
    path = os.path.join(exp_root, "pressure_summary.csv")
    if not os.path.exists(path):
        return
    rows = _read_csv(path)
    rows = [r for r in rows if r["cache"] == "LRU"]
    if not rows:
        return

    fig, ax = plt.subplots(figsize=(8.5, 4.2))
    for ds in sorted({r["dataset"] for r in rows}):
        sub = sorted([r for r in rows if r["dataset"] == ds], key=lambda r: int(float(r["capacity"])))
        ax.plot(
            [int(float(r["capacity"])) for r in sub],
            [float(r["suppression_rate"]) for r in sub],
            marker="o",
            linewidth=2.2,
            label=ds,
        )
    ax.set_xscale("log", base=2)
    ax.set_xlabel("Cache capacity")
    ax.set_ylabel("Suppression rate")
    ax.set_title("Exp2 pressure: LRU suppression across workload conditions")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8)
    _save(fig, out_dir, "exp2_lru_dataset_comparison.png")

    fig, ax = plt.subplots(figsize=(8.5, 4.2))
    for ds in sorted({r["dataset"] for r in rows}):
        sub = sorted([r for r in rows if r["dataset"] == ds], key=lambda r: int(float(r["capacity"])))
        ax.plot(
            [int(float(r["capacity"])) for r in sub],
            [float(r["gap_to_oracle"]) for r in sub],
            marker="o",
            linewidth=2.2,
            label=ds,
        )
    ax.set_xscale("log", base=2)
    ax.set_xlabel("Cache capacity")
    ax.set_ylabel("Gap-to-oracle")
    ax.set_title("Exp2 pressure: LRU gap-to-oracle across workload conditions")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8)
    _save(fig, out_dir, "exp2_lru_gap_to_oracle_comparison.png")


def plot_exp3(exp_root, out_dir):
    path = os.path.join(exp_root, "admission_deltas_vs_lru.csv")
    if not os.path.exists(path):
        return
    rows = _read_csv(path)
    if not rows:
        return

    caps = sorted({int(float(r["capacity"])) for r in rows})
    cap_pick = 128 if 128 in caps else caps[min(len(caps) - 1, len(caps) // 2)]

    grouped = [r for r in rows if int(float(r["capacity"])) == cap_pick]
    policies = sorted({r["cache"] for r in grouped})
    datasets = sorted({r["dataset"] for r in grouped})

    fig, ax = plt.subplots(figsize=(10, 4.8))
    width = 0.8 / max(1, len(datasets))
    x_idx = list(range(len(policies)))
    for j, ds in enumerate(datasets):
        vals = []
        by_pol = {r["cache"]: float(r["suppression_gain_vs_lru"]) for r in grouped if r["dataset"] == ds}
        for p in policies:
            vals.append(by_pol.get(p, 0.0))
        xs = [x + (j - (len(datasets) - 1) / 2) * width for x in x_idx]
        ax.bar(xs, vals, width=width, label=ds)
    ax.axhline(0.0, color="#333333", linewidth=1.0)
    ax.set_xticks(x_idx)
    ax.set_xticklabels(policies, rotation=35, ha="right")
    ax.set_ylabel("Suppression gain vs LRU")
    ax.set_title(f"Exp3 admission deltas vs LRU at capacity={cap_pick}")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(fontsize=8)
    _save(fig, out_dir, "exp3_policy_gain_vs_lru_comparison.png")


def plot_exp4(exp_root, out_dir):
    path = os.path.join(exp_root, "ttl_freshness_summary.csv")
    if not os.path.exists(path):
        return
    rows = _read_csv(path)
    if not rows:
        return

    focus = {
        "LRU",
        "FlowLifetimeAdaptiveTTL",
        "CacheINTFreshnessLRU",
        "FreshnessInvalidationLRU",
        "LRUTtl(2ms)",
        "LRUTtl(10ms)",
    }
    rows = [r for r in rows if r["cache"] in focus]

    fig, ax = plt.subplots(figsize=(8.5, 4.2))
    datasets = sorted({r["dataset"] for r in rows})
    for ds in datasets:
        sub = sorted([r for r in rows if r["dataset"] == ds and r["cache"] == "FlowLifetimeAdaptiveTTL"], key=lambda r: int(float(r["capacity"])))
        if not sub:
            continue
        ax.plot(
            [int(float(r["capacity"])) for r in sub],
            [float(r["suppression_rate"]) for r in sub],
            marker="o",
            linewidth=2.0,
            label=f"{ds} / FlowLifetimeAdaptiveTTL",
        )
        lru = sorted([r for r in rows if r["dataset"] == ds and r["cache"] == "LRU"], key=lambda r: int(float(r["capacity"])))
        if lru:
            ax.plot(
                [int(float(r["capacity"])) for r in lru],
                [float(r["suppression_rate"]) for r in lru],
                marker=".",
                linewidth=1.6,
                linestyle="--",
                label=f"{ds} / LRU",
            )
    ax.set_xscale("log", base=2)
    ax.set_xlabel("Cache capacity")
    ax.set_ylabel("Suppression rate")
    ax.set_title("Exp4 TTL/freshness: adaptive TTL vs LRU across conditions")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=7)
    _save(fig, out_dir, "exp4_ttl_vs_lru_comparison.png")


def main():
    ap = argparse.ArgumentParser(description="Generate experiment comparison plots.")
    ap.add_argument("--experiment", required=True, choices=["exp1", "exp2", "exp3", "exp4"])
    ap.add_argument("--exp-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--flow-stats-csv", default="")
    args = ap.parse_args()

    if args.experiment == "exp1":
        plot_exp1(args.exp_root, args.out, args.flow_stats_csv)
    elif args.experiment == "exp2":
        plot_exp2(args.exp_root, args.out)
    elif args.experiment == "exp3":
        plot_exp3(args.exp_root, args.out)
    else:
        plot_exp4(args.exp_root, args.out)


if __name__ == "__main__":
    main()
