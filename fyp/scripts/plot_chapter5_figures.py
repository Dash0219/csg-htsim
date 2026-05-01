#!/usr/bin/env python3
"""
Generate chapter-5 figures:
  obs1_skew_sweep.png     - suppression vs sigma (oracle/LRU/best, with 95CI)
  obs2_burst_sweep.png    - suppression vs burst  (oracle/LRU/best, with 95CI)
  obs3_cliff_sweep.png    - suppression vs capacity for incast_mono_64 (cliff effect)
  obs8_policy_ranking.png - mean eta vs capacity (all policies, rainbow gradient)
"""

import os
import glob
import re
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

FINDINGS = os.path.join(os.path.dirname(__file__), "../experiments/findings")
OUT_DIR  = os.path.join(os.path.dirname(__file__), "../report/FYP/img")

C_ORACLE = "#ff0045"
C_LRU    = "#ffd543"
C_BEST   = "#86cecb"

CAP_256 = 256

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def load_csv(path):
    df = pd.read_csv(path)
    df.columns = df.columns.str.strip()
    return df


def best_at_cap(df, cap):
    """Return (policy_name, suppression_rate) for the highest non-oracle policy at `cap`."""
    sub = df[(df["capacity"] == cap) & (df["cache"] != "Infinite")]
    if sub.empty:
        return None, np.nan
    idx = sub["suppression_rate"].idxmax()
    row = sub.loc[idx]
    return row["cache"], row["suppression_rate"]


def get_oracle(df, cap=-1):
    row = df[(df["cache"] == "Infinite") & (df["capacity"] == cap)]
    if row.empty:
        return np.nan, np.nan
    return row["suppression_rate"].values[0], row["suppression_rate_ci95"].values[0]


def get_lru(df, cap):
    row = df[(df["cache"] == "LRU") & (df["capacity"] == cap)]
    if row.empty:
        return np.nan, np.nan
    return row["suppression_rate"].values[0], row["suppression_rate_ci95"].values[0]


def get_best(df, cap):
    """Highest-suppression non-oracle policy at cap, returns (val, ci95)."""
    sub = df[(df["capacity"] == cap) & (df["cache"] != "Infinite")]
    if sub.empty:
        return np.nan, np.nan
    idx = sub["suppression_rate"].idxmax()
    row = sub.loc[idx]
    return row["suppression_rate"], row["suppression_rate_ci95"]


def plot_sweep(xs, oracle_vals, oracle_ci, lru_vals, lru_ci, best_vals, best_ci,
               xlabel, xticklabels, title, out_path, xlog=False):
    fig, ax = plt.subplots(figsize=(6, 3.8))

    xs_arr = np.array(xs, dtype=float)

    for vals, ci, color, label in [
        (oracle_vals, oracle_ci, C_ORACLE, "Oracle"),
        (lru_vals,    lru_ci,    C_LRU,    "LRU (cap=256)"),
        (best_vals,   best_ci,   C_BEST,   "Best policy (cap=256)"),
    ]:
        v = np.array(vals) * 100
        c = np.array(ci)   * 100
        ax.plot(xs_arr, v, color=color, linewidth=2, marker="o", markersize=5, label=label)
        ax.fill_between(xs_arr, v - c, v + c, color=color, alpha=0.2)

    ax.set_xlabel(xlabel, fontsize=11)
    ax.set_ylabel("Suppression rate (%)", fontsize=11)
    ax.set_ylim(0, 105)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    if xlog:
        ax.set_xscale("log", base=2)
        ax.set_xticks(xs_arr)
        ax.get_xaxis().set_major_formatter(mticker.ScalarFormatter())

    if xticklabels:
        ax.set_xticks(xs_arr)
        ax.set_xticklabels(xticklabels)

    ax.legend(frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out_path}")


# ---------------------------------------------------------------------------
# Plot 1: skew sweep
# ---------------------------------------------------------------------------

def plot_skew():
    skew_dir = os.path.join(FINDINGS, "3_skew_sweep")
    pattern  = os.path.join(skew_dir, "mean_ci95_ndp_incast_heavytail_sigma_*.csv")
    files    = sorted(glob.glob(pattern))

    sigmas, oracle_v, oracle_c, lru_v, lru_c, best_v, best_c = [], [], [], [], [], [], []
    for f in files:
        m = re.search(r"sigma_(\d+p\d+)", f)
        if not m:
            continue
        sigma = float(m.group(1).replace("p", "."))
        df = load_csv(f)
        ov, oc = get_oracle(df)
        lv, lc = get_lru(df, CAP_256)
        bv, bc = get_best(df, CAP_256)
        sigmas.append(sigma)
        oracle_v.append(ov); oracle_c.append(oc)
        lru_v.append(lv);    lru_c.append(lc)
        best_v.append(bv);   best_c.append(bc)

    out = os.path.join(OUT_DIR, "obs1_skew_sweep.png")
    plot_sweep(sigmas, oracle_v, oracle_c, lru_v, lru_c, best_v, best_c,
               xlabel=r"Lognormal shape $\sigma$",
               xticklabels=[str(s) for s in sigmas],
               title="Skew sweep", out_path=out)


# ---------------------------------------------------------------------------
# Plot 2: burst sweep
# ---------------------------------------------------------------------------

def plot_burst():
    burst_dir = os.path.join(FINDINGS, "2_burst_sweep")
    pattern   = os.path.join(burst_dir, "mean_ci95_ndp_incast_heavytail_burst_*.csv")
    files     = sorted(glob.glob(pattern), key=lambda f: int(re.search(r"burst_(\d+)", f).group(1)))

    bursts, oracle_v, oracle_c, lru_v, lru_c, best_v, best_c = [], [], [], [], [], [], []
    for f in files:
        m = re.search(r"burst_(\d+)", f)
        burst = int(m.group(1))
        df = load_csv(f)
        ov, oc = get_oracle(df)
        lv, lc = get_lru(df, CAP_256)
        bv, bc = get_best(df, CAP_256)
        bursts.append(burst)
        oracle_v.append(ov); oracle_c.append(oc)
        lru_v.append(lv);    lru_c.append(lc)
        best_v.append(bv);   best_c.append(bc)

    out = os.path.join(OUT_DIR, "obs2_burst_sweep.png")
    plot_sweep(bursts, oracle_v, oracle_c, lru_v, lru_c, best_v, best_c,
               xlabel="Path-burst length (packets, log₂ scale)",
               xticklabels=None,
               title="Burst sweep", out_path=out, xlog=True)


# ---------------------------------------------------------------------------
# Plot 3: cliff sweep — suppression vs capacity for incast_mono_64
# ---------------------------------------------------------------------------

def plot_cliff():
    cliff_csv = os.path.join(FINDINGS, "1_flow_size_sweep", "mean_ci95_ndp_incast_mono_64.csv")
    df = load_csv(cliff_csv)

    # All finite capacities in sorted order (exclude -1 = infinite oracle)
    caps = sorted(df[df["capacity"] > 0]["capacity"].unique())

    oracle_row = df[df["capacity"] == -1]
    oracle_sup = oracle_row["suppression_rate"].values[0] if not oracle_row.empty else np.nan
    oracle_ci  = oracle_row["suppression_rate_ci95"].values[0] if not oracle_row.empty else np.nan

    # Policies to show: oracle (flat line), LRU, TinyLFULRU (best)
    # Exclude archived policies (FIFO, LFU, OnlineAdaptiveAdmissionLRU)
    EXCLUDE = {"FIFO", "LFU", "OnlineAdaptiveAdmissionLRU", "Infinite"}

    lru_v, lru_c, best_v, best_c = [], [], [], []
    for cap in caps:
        sub = df[df["capacity"] == cap]
        lru_row = sub[sub["cache"] == "LRU"]
        lv = lru_row["suppression_rate"].values[0] if not lru_row.empty else np.nan
        lc = lru_row["suppression_rate_ci95"].values[0] if not lru_row.empty else np.nan
        lru_v.append(lv); lru_c.append(lc)

        best_sub = sub[~sub["cache"].isin(EXCLUDE)]
        if best_sub.empty:
            best_v.append(np.nan); best_c.append(np.nan)
        else:
            idx = best_sub["suppression_rate"].idxmax()
            row = best_sub.loc[idx]
            best_v.append(row["suppression_rate"])
            best_c.append(row["suppression_rate_ci95"])

    xs = np.array(caps, dtype=float)
    oracle_arr = np.array([oracle_sup] * len(caps)) * 100
    oracle_ci_arr = np.array([oracle_ci] * len(caps)) * 100
    lru_arr  = np.array(lru_v) * 100
    lru_ci_arr = np.array(lru_c) * 100
    best_arr = np.array(best_v) * 100
    best_ci_arr = np.array(best_c) * 100

    fig, ax = plt.subplots(figsize=(6, 3.8))
    for arr, ci_arr, color, label in [
        (oracle_arr, oracle_ci_arr, C_ORACLE, "Oracle"),
        (lru_arr,    lru_ci_arr,    C_LRU,    "LRU"),
        (best_arr,   best_ci_arr,   C_BEST,   "Best policy (TinyLFULRU)"),
    ]:
        ax.plot(xs, arr, color=color, linewidth=2, marker="o", markersize=5, label=label)
        ax.fill_between(xs, arr - ci_arr, arr + ci_arr, color=color, alpha=0.2)

    # Mark the cliff at cap=512 (where all 512 concurrent flows fit)
    ax.axvline(512, color="#888888", linewidth=1, linestyle=":", zorder=1)
    ax.text(512 * 1.05, 5, "cap = 512\n(= flow count)", fontsize=7.5, color="#555555", va="bottom")

    ax.set_xscale("log", base=2)
    ax.set_xticks(xs)
    ax.get_xaxis().set_major_formatter(mticker.ScalarFormatter())
    ax.set_xlabel("Cache capacity (entries, log₂ scale)", fontsize=11)
    ax.set_ylabel("Suppression rate (%)", fontsize=11)
    ax.set_ylim(0, 105)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(frameon=False, fontsize=9)
    fig.tight_layout()

    out = os.path.join(OUT_DIR, "obs3_cliff_sweep.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out}")


# ---------------------------------------------------------------------------
# Plot 4: policy ranking — mean eta vs capacity
# ---------------------------------------------------------------------------

def plot_ranking():
    rank_dir = os.path.join(FINDINGS, "8_policy_ranking")
    files    = sorted(glob.glob(os.path.join(rank_dir, "*.csv")))
    dfs = [load_csv(f) for f in files]

    ARCHIVED = {"FIFO", "LFU", "OnlineAdaptiveAdmissionLRU"}
    all_policies = sorted({p for df in dfs for p in df["cache"].unique()
                           if p != "Infinite" and p not in ARCHIVED})

    # Compute mean eta at cap=256 across all datasets
    eta256 = {}
    for policy in all_policies:
        vals = []
        for df in dfs:
            oracle_row = df[(df["cache"] == "Infinite") & (df["capacity"] == -1)]
            if oracle_row.empty:
                continue
            oracle_val = oracle_row["suppression_rate"].values[0]
            if oracle_val == 0:
                continue
            row = df[(df["cache"] == policy) & (df["capacity"] == 256)]
            if row.empty:
                continue
            vals.append(row["suppression_rate"].values[0] / oracle_val)
        eta256[policy] = np.mean(vals) if vals else np.nan

    # Sort best-to-worst (top of chart = rank 1 → invert for barh)
    ranked = sorted(all_policies, key=lambda p: eta256[p], reverse=False)
    lru_val = eta256.get("LRU", np.nan)

    vals  = [eta256[p] * 100 for p in ranked]
    lru_pct = lru_val * 100

    # Colour: above-LRU teal, LRU gold, below-LRU red
    C_ABOVE   = "#86cecb"
    C_BASELINE= "#ffd543"
    C_BELOW   = "#ff0045"
    bar_colors = []
    for p in ranked:
        v = eta256[p]
        if abs(v - lru_val) < 1e-6:  # treat as equal if within 0.1pp
            bar_colors.append(C_BASELINE)
        elif v > lru_val:
            bar_colors.append(C_ABOVE)
        else:
            bar_colors.append(C_BELOW)

    fig, ax = plt.subplots(figsize=(7, 5.5))
    ys = np.arange(len(ranked))
    bars = ax.barh(ys, vals, color=bar_colors, edgecolor="none", height=0.7)

    # Vertical line at LRU
    ax.axvline(lru_pct, color=C_BASELINE, linewidth=1.2, linestyle="--", zorder=3)

    # Value labels at end of each bar
    for bar, v in zip(bars, vals):
        ax.text(v + 0.3, bar.get_y() + bar.get_height() / 2,
                f"{v:.1f}%", va="center", ha="left", fontsize=7.5)

    ax.set_yticks(ys)
    ax.set_yticklabels(ranked, fontsize=8.5)
    ax.set_xlabel("Mean cache efficiency η at cap=256 (%)", fontsize=11)
    ax.set_xlim(0, 105)
    ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax.grid(axis="x", linestyle="--", alpha=0.35)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Legend
    from matplotlib.patches import Patch
    legend_handles = [
        Patch(facecolor=C_ABOVE,    label="Above LRU baseline"),
        Patch(facecolor=C_BASELINE, label="LRU (baseline)"),
        Patch(facecolor=C_BELOW,    label="Below LRU baseline"),
    ]
    # ax.legend(handles=legend_handles, frameon=False, fontsize=8.5, loc="lower left")

    fig.tight_layout()
    out = os.path.join(OUT_DIR, "obs8_policy_ranking.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out}")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Plotting obs1 skew sweep...")
    plot_skew()
    print("Plotting obs2 burst sweep...")
    plot_burst()
    print("Plotting obs3 cliff sweep...")
    plot_cliff()
    print("Plotting obs8 policy ranking...")
    plot_ranking()
    print("Done.")
