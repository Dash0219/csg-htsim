#!/usr/bin/env python3
"""
Generate three chapter-5 figures:
  obs1_skew_sweep.png    - suppression vs sigma (oracle/LRU/best, with 95CI)
  obs2_burst_sweep.png   - suppression vs burst  (oracle/LRU/best, with 95CI)
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

FINDINGS = os.path.join(os.path.dirname(__file__), "../dash_experiments/findings")
OUT_DIR  = os.path.join(os.path.dirname(__file__), "../dash_report/img")

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
# Plot 3: policy ranking — mean eta vs capacity
# ---------------------------------------------------------------------------

def plot_ranking():
    rank_dir = os.path.join(FINDINGS, "8_policy_ranking")
    files    = sorted(glob.glob(os.path.join(rank_dir, "*.csv")))
    dfs = [load_csv(f) for f in files]

    all_policies = sorted({p for df in dfs for p in df["cache"].unique() if p != "Infinite"})

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
    print("Plotting obs3 policy ranking...")
    plot_ranking()
    print("Done.")
