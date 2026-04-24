"""Plot per-flow size-frequency distributions from synthetic INT logs."""

import argparse
import bisect
import math
import os
import re
from collections import defaultdict

LOW_TEMP_SUFFIX = "low_temp_locality"


def all_dataset_names(include_low_temp=True):
    names = [
        "incast_mono",
        "a2a_mono",
        "incast_bimodal",
        "a2a_bimodal",
        "incast_pareto",
        "a2a_pareto",
        "incast_heavytail",
        "a2a_heavytail",
        "incast_exponential_skewed",
        "a2a_exponential_skewed",
    ]
    if include_low_temp:
        names.extend(f"{n}_{LOW_TEMP_SUFFIX}" for n in list(names))
    return names


def default_dataset_names(low_temp_locality=False):
    names = all_dataset_names(include_low_temp=False)
    if low_temp_locality:
        return [f"{n}_{LOW_TEMP_SUFFIX}" for n in names]
    return names


def dataset_log_path(dataset_name, logs_dir):
    return os.path.join(logs_dir, f"log_{dataset_name}.txt")


def parse_flow_ids(path):
    """Yield flow IDs for each INT record in log."""
    header_re = re.compile(r"INT flow=(\d+) seq=(\d+) hops=(\d+)")
    with open(path) as f:
        for line in f:
            hm = header_re.search(line)
            if hm:
                yield int(hm.group(1))


def flow_record_counts(path):
    """Return list of per-flow record counts."""
    counts = defaultdict(int)
    for flow in parse_flow_ids(path):
        counts[flow] += 1
    return list(counts.values())


def percentile(sorted_vals, p):
    """Nearest-rank percentile for p in [0, 100]."""
    if not sorted_vals:
        return 0
    if p <= 0:
        return sorted_vals[0]
    if p >= 100:
        return sorted_vals[-1]
    idx = int(math.ceil((p / 100.0) * len(sorted_vals))) - 1
    idx = max(0, min(idx, len(sorted_vals) - 1))
    return sorted_vals[idx]


def summarize(values):
    """Basic summary stats for records-per-flow list."""
    sv = sorted(values)
    n = len(sv)
    total = sum(sv)
    mean = total / n if n else 0.0
    return {
        "flows": n,
        "records": total,
        "mean": mean,
        "median": percentile(sv, 50),
        "p90": percentile(sv, 90),
        "p99": percentile(sv, 99),
        "max": sv[-1] if sv else 0,
    }


def build_pow2_bins(max_val):
    """Histogram bins: powers of two from 1 up to > max_val."""
    bins = [1]
    while bins[-1] <= max_val:
        bins.append(bins[-1] * 2)
    return bins


def binned_frequency(values, bins):
    """Count flows per bin where bins define [bins[i], bins[i+1])."""
    freq = [0] * (len(bins) - 1)
    for v in values:
        idx = bisect.bisect_right(bins, v) - 1
        idx = max(0, min(idx, len(freq) - 1))
        freq[idx] += 1
    return freq


def bin_labels(bins):
    """Readable labels for power-of-two bins."""
    labels = []
    for i in range(len(bins) - 1):
        lo = bins[i]
        hi = bins[i + 1] - 1
        if lo == hi:
            labels.append(str(lo))
        else:
            labels.append(f"{lo}-{hi}")
    return labels


def compute_ccdf(values):
    """Return (x, ccdf_y) arrays for a CCDF plot over sorted unique values."""
    if not values:
        return [], []
    sv = sorted(values)
    n = len(sv)
    # unique x points with P(X > x)
    xs = []
    ys = []
    prev = None
    for i, v in enumerate(sv):
        if v != prev:
            xs.append(v)
            ys.append(1.0 - i / n)
            prev = v
    xs.append(sv[-1] + 1)
    ys.append(0.0)
    return xs, ys


def base_dataset_name(name):
    suffix = f"_{LOW_TEMP_SUFFIX}"
    if name.endswith(suffix):
        return name[: -len(suffix)]
    return name


def natural_sort_key(name):
    """Sort mixed alpha/numeric dataset names in a human-readable order."""
    parts = re.split(r"(\d+)", name)
    key = []
    for part in parts:
        if part.isdigit():
            key.append(int(part))
        else:
            key.append(part)
    return key


def ordered_present_names(data):
    """Known datasets first, then any additional sweep datasets."""
    preferred = all_dataset_names(include_low_temp=True)
    present = [name for name in preferred if name in data]
    extra = sorted((name for name in data if name not in present), key=natural_sort_key)
    return present + extra


COLOR_MAP = {
    "incast_mono": "tab:blue",
    "a2a_mono": "tab:orange",
    "incast_bimodal": "tab:green",
    "a2a_bimodal": "mediumseagreen",
    "incast_pareto": "tab:red",
    "a2a_pareto": "salmon",
    "incast_heavytail": "tab:purple",
    "a2a_heavytail": "mediumpurple",
    "incast_exponential_skewed": "tab:cyan",
    "a2a_exponential_skewed": "deepskyblue",
}


def _color_for(name):
    key = base_dataset_name(name)
    if key in COLOR_MAP:
        return COLOR_MAP[key]
    if key.startswith("incast_"):
        return "tab:blue"
    if key.startswith("a2a_"):
        return "tab:orange"
    return "tab:gray"


def plot_dataset(name, vals, bins, labels, out_dir, prefix, log_y, show):
    """Save a 1x2 figure (bar chart + CCDF) for a single dataset."""
    try:
        import matplotlib
        if not show:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        raise RuntimeError("matplotlib is required. Install with: pip install matplotlib")

    os.makedirs(out_dir, exist_ok=True)

    freq = binned_frequency(vals, bins)
    xs_ccdf, ys_ccdf = compute_ccdf(vals)

    color = _color_for(name)
    x = list(range(len(labels)))

    fig, (ax_bar, ax_ccdf) = plt.subplots(1, 2, figsize=(10, 3.8))

    # --- left: bar chart ---
    ax_bar.bar(x, freq, color=color, alpha=0.85)
    ax_bar.set_title("Flow size histogram")
    ax_bar.set_xlabel("Flow size bin (records/flow)")
    ax_bar.set_ylabel("# flows")
    ax_bar.set_xticks(x)
    ax_bar.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax_bar.grid(True, axis="y", alpha=0.25)
    if log_y:
        ax_bar.set_yscale("log")
        ax_bar.set_ylabel("# flows (log scale)")

    # --- right: CCDF ---
    ax_ccdf.step(xs_ccdf, ys_ccdf, where="post", color=color, linewidth=1.6)
    ax_ccdf.set_title("Flow size CCDF")
    ax_ccdf.set_xlabel("Flow size (records/flow)")
    ax_ccdf.set_ylabel("P(X > x)")
    ax_ccdf.set_xscale("log")
    ax_ccdf.set_yscale("log")
    ax_ccdf.grid(True, which="both", alpha=0.2)
    ax_ccdf.set_ylim(bottom=max(1e-4, 1.0 / (len(vals) * 10)) if vals else 1e-4)

    fig.suptitle(name, y=1.01, fontsize=11)
    fig.tight_layout()

    safe_name = re.sub(r"[^A-Za-z0-9_\-]", "_", name)
    out_path = os.path.join(out_dir, f"{safe_name}_flow_size.png")
    fig.savefig(out_path, dpi=160, bbox_inches="tight")
    if show:
        plt.show()
    plt.close(fig)
    return out_path


def plot_distributions(data, out_dir, prefix, log_y=True, show=False):
    """Save one PNG per dataset plus a combined multi-panel figure."""
    try:
        import matplotlib
        if not show:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        raise RuntimeError("matplotlib is required. Install with: pip install matplotlib")

    os.makedirs(out_dir, exist_ok=True)

    global_max = max(max(vals) for vals in data.values() if vals)
    bins = build_pow2_bins(global_max)
    labels = bin_labels(bins)

    present = ordered_present_names(data)
    saved = []

    for name in present:
        vals = data.get(name, [])
        if not vals:
            continue
        path = plot_dataset(name, vals, bins, labels, out_dir, prefix, log_y, show)
        saved.append(path)

    return saved


def main():
    ap = argparse.ArgumentParser(
        description="Plot synthetic flow-size distributions from INT logs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument(
        "-d",
        "--dataset",
        action="append",
        default=[],
        help="Only plot selected synthetic dataset name(s); repeatable",
    )
    ap.add_argument(
        "-l",
        "--low-temp-locality",
        action="store_true",
        help="Plot low-temp-locality synthetic datasets",
    )
    ap.add_argument("--logs-dir", default="fyp/dash_dataset/synthetic", help="Directory containing log_<dataset>.txt files")
    ap.add_argument("--out-dir", default="fyp/dash_results/synthetic/flow_size/plots", help="Output directory for figures")
    ap.add_argument("--prefix", default="flow_size", help="Output filename prefix")
    ap.add_argument(
        "--log-y",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use logarithmic y-axis on bar chart (default: on)",
    )
    ap.add_argument("--show", action="store_true", help="Show plots interactively")
    args = ap.parse_args()

    if args.dataset:
        selected = []
        for d in args.dataset:
            if d == "incast":
                d = "incast_mono"
            elif d == "a2a":
                d = "a2a_mono"
            elif d == f"incast_{LOW_TEMP_SUFFIX}":
                d = f"incast_mono_{LOW_TEMP_SUFFIX}"
            elif d == f"a2a_{LOW_TEMP_SUFFIX}":
                d = f"a2a_mono_{LOW_TEMP_SUFFIX}"
            if args.low_temp_locality and not d.endswith(f"_{LOW_TEMP_SUFFIX}"):
                d = f"{d}_{LOW_TEMP_SUFFIX}"
            selected.append(d)
        names = selected
    else:
        names = default_dataset_names(low_temp_locality=args.low_temp_locality)

    patterns = {name: dataset_log_path(name, args.logs_dir) for name in names}

    data = {}
    print("=== Loading flow distributions ===")
    for name, path in patterns.items():
        if not os.path.exists(path):
            print(f"{name:<14} file={path:<12} MISSING (skipped)")
            continue
        vals = flow_record_counts(path)
        data[name] = vals
        s = summarize(vals)
        print(
            f"{name:<8} file={path:<12} flows={s['flows']:,} records={s['records']:,} "
            f"mean={s['mean']:.1f} median={s['median']} p90={s['p90']} p99={s['p99']} max={s['max']}"
        )

    if not data:
        raise RuntimeError("No input logs found. Provide valid paths for at least one pattern.")

    saved = plot_distributions(
        data, args.out_dir, args.prefix, log_y=args.log_y, show=args.show
    )
    print("\nSaved figures:")
    for p in saved:
        print(f"  {p}")


if __name__ == "__main__":
    main()
