#!/usr/bin/env python3
"""Plot per-flow lifetime distributions from synthetic INT logs."""

import argparse
import os
import re
from collections import defaultdict

LOW_TEMP_SUFFIX = "low_temp_locality"


def is_supported_dataset_name(name):
    if name in set(synthetic_dataset_names(include_low_temp=True)):
        return True
    if re.match(r"^(incast|a2a)_pareto_temp_[0-9]+$", name):
        return True
    if re.match(r"^(incast|a2a)_pareto_alpha_[0-9]+(?:p[0-9]+)?$", name):
        return True
    if re.match(r"^(incast|a2a)_pareto_xm_[0-9]+$", name):
        return True
    return False


def discover_synthetic_logfiles(logs_dir, low_temp_only=False, include_low_temp=False):
    if not os.path.isdir(logs_dir):
        return []
    out = []
    for name in sorted(os.listdir(logs_dir)):
        if not (name.startswith("log_") and name.endswith(".txt")):
            continue
        ds = name[4:-4]
        if low_temp_only and not ds.endswith(f"_{LOW_TEMP_SUFFIX}"):
            continue
        if not include_low_temp and ds.endswith(f"_{LOW_TEMP_SUFFIX}"):
            continue
        out.append(os.path.join(logs_dir, name))
    return out


def synthetic_dataset_names(include_low_temp=False):
    names = [
        "incast_mono",
        "a2a_mono",
        "incast_bimodal",
        "a2a_bimodal",
        "incast_pareto",
        "a2a_pareto",
        "incast_exponential_skewed",
        "a2a_exponential_skewed",
    ]
    if include_low_temp:
        names.extend(f"{n}_{LOW_TEMP_SUFFIX}" for n in list(names))
    return names


def synthetic_log_path(dataset_name, logs_dir="dash_dataset/synthetic"):
    return os.path.join(logs_dir, f"log_{dataset_name}.txt")


def normalize_dataset_alias(name):
    if name == "incast":
        return "incast_mono"
    if name == "a2a":
        return "a2a_mono"
    if name == f"incast_{LOW_TEMP_SUFFIX}":
        return f"incast_mono_{LOW_TEMP_SUFFIX}"
    if name == f"a2a_{LOW_TEMP_SUFFIX}":
        return f"a2a_mono_{LOW_TEMP_SUFFIX}"
    return name


def parse_int_records(path):
    token_re = re.compile(
        r"INT flow=(?P<flow>\d+) seq=(?P<seq>\d+) hops=(?P<hops>\d+)"
        r"|\[(?P<idx>\d+)\] sw=(?P<sw>\d+) type=(?P<typ>\d+) qs=(?P<qs>\d+) ts=(?P<ts>\d+) txbytes=(?P<txbytes>\d+) pktid=(?P<pktid>\d+)"
    )

    current = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            for m in token_re.finditer(line):
                if m.group("flow") is not None:
                    if current is not None:
                        yield current
                    current = {
                        "flow": int(m.group("flow")),
                        "seq": int(m.group("seq")),
                        "ts": [],
                    }
                    continue

                if current is None:
                    continue
                current["ts"].append(int(m.group("ts")))

    if current is not None:
        yield current


def collect_lifetimes_us(records, max_records=0):
    windows = {}
    count = 0
    for rec in records:
        if max_records > 0 and count >= max_records:
            break
        count += 1
        if not rec["ts"]:
            continue
        flow = rec["flow"]
        ts = rec["ts"][-1]
        if flow not in windows:
            windows[flow] = [ts, ts]
        else:
            if ts < windows[flow][0]:
                windows[flow][0] = ts
            if ts > windows[flow][1]:
                windows[flow][1] = ts

    lifetimes_us = []
    for start_ts, end_ts in windows.values():
        lt_us = max(0.0, (end_ts - start_ts) / 1_000_000.0)
        lifetimes_us.append(lt_us)

    lifetimes_us.sort()
    return lifetimes_us


def percentile(sorted_vals, p):
    if not sorted_vals:
        return 0.0
    if p <= 0.0:
        return sorted_vals[0]
    if p >= 1.0:
        return sorted_vals[-1]
    idx = int((len(sorted_vals) - 1) * p)
    return sorted_vals[idx]


def sanitize_name(path):
    base = os.path.splitext(os.path.basename(path))[0]
    if base.startswith("log_"):
        base = base[4:]
    return base


def parse_args():
    ap = argparse.ArgumentParser(
        description="Plot per-flow lifetime distributions from INT logs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("logfiles", nargs="*", help="INT log file(s)")
    ap.add_argument(
        "-d",
        "--dataset",
        action="append",
        default=[],
        help="Synthetic dataset name to plot (repeatable)",
    )
    ap.add_argument(
        "-l",
        "--low-temp-locality",
        action="store_true",
        help="Select low-temp-locality synthetic datasets",
    )
    ap.add_argument(
        "--synthetic-defaults",
        action="store_true",
        help="Plot built-in synthetic logs (default behavior when no logfile is provided)",
    )
    ap.add_argument(
        "--include-low-temp-defaults",
        action="store_true",
        help="When using synthetic defaults, also include *_low_temp_locality datasets",
    )
    ap.add_argument(
        "--logs-dir",
        default="dash_dataset/synthetic",
        help="Directory containing synthetic log_<dataset>.txt files",
    )
    ap.add_argument(
        "--out-dir",
        default="dash_results/synthetic/flow_lifetime/plots",
        help="Output directory for PNGs",
    )
    ap.add_argument("--prefix", default="flow_lifetime", help="Output filename prefix")
    ap.add_argument("--max-records", type=int, default=0, help="Only use first N records (0 means all)")
    ap.add_argument("--bins", type=int, default=50, help="Histogram bin count")
    return ap.parse_args()


def main():
    args = parse_args()

    selected_datasets = []
    for d in args.dataset:
        d = normalize_dataset_alias(d)
        if args.low_temp_locality and not d.endswith(f"_{LOW_TEMP_SUFFIX}"):
            selected_datasets.append(f"{d}_{LOW_TEMP_SUFFIX}")
        else:
            selected_datasets.append(d)

    unknown = [d for d in selected_datasets if not is_supported_dataset_name(d)]
    if unknown:
        raise ValueError(f"Unknown dataset name(s): {', '.join(unknown)}")

    if args.logfiles:
        logfiles = list(args.logfiles)
    else:
        logfiles = []
        if selected_datasets:
            logfiles.extend(synthetic_log_path(d, args.logs_dir) for d in selected_datasets)
        elif args.synthetic_defaults or not args.logfiles:
            if args.low_temp_locality:
                logfiles.extend(discover_synthetic_logfiles(args.logs_dir, low_temp_only=True, include_low_temp=True))
            elif args.include_low_temp_defaults:
                logfiles.extend(discover_synthetic_logfiles(args.logs_dir, include_low_temp=True))
            else:
                logfiles.extend(discover_synthetic_logfiles(args.logs_dir, include_low_temp=False))

    deduped = []
    seen = set()
    for p in logfiles:
        if p in seen:
            continue
        seen.add(p)
        deduped.append(p)
    logfiles = deduped

    os.makedirs(args.out_dir, exist_ok=True)

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError("matplotlib is required. Install with: pip install matplotlib") from exc

    generated = 0
    skipped = 0

    for logfile in logfiles:
        if not os.path.exists(logfile):
            print(f"Skipping missing input: {logfile}")
            skipped += 1
            continue

        records = parse_int_records(logfile)
        lifetimes_us = collect_lifetimes_us(records, max_records=args.max_records)
        if not lifetimes_us:
            print(f"Skipping empty/non-parseable input: {logfile}")
            skipped += 1
            continue

        title_name = sanitize_name(logfile)

        p50 = percentile(lifetimes_us, 0.50)
        p90 = percentile(lifetimes_us, 0.90)
        p99 = percentile(lifetimes_us, 0.99)
        max_lt = lifetimes_us[-1]

        # 2-panel figure: histogram + CCDF for complementary views.
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.5, 4.8))

        hist_vals = [max(v, 1e-6) for v in lifetimes_us]
        ax1.hist(hist_vals, bins=args.bins, color="#1f77b4", alpha=0.85)
        ax1.set_xscale("log")
        ax1.set_xlabel("flow lifetime (us)")
        ax1.set_ylabel("# flows")
        ax1.set_title("Lifetime histogram")
        ax1.grid(True, alpha=0.3)

        n = len(lifetimes_us)
        x = [max(v, 1e-6) for v in lifetimes_us]
        y = [1.0 - (i + 1) / n for i in range(n)]
        ax2.plot(x, y, color="#d62728", linewidth=1.6)
        ax2.set_xscale("log")
        ax2.set_yscale("log")
        ax2.set_xlabel("flow lifetime (us)")
        ax2.set_ylabel("CCDF")
        ax2.set_title("Lifetime tail (CCDF)")
        ax2.grid(True, which="both", alpha=0.3)

        fig.suptitle(
            f"Flow lifetime distribution ({title_name}) | flows={n:,} p50={p50:.3f}us p90={p90:.3f}us p99={p99:.3f}us max={max_lt:.3f}us",
            y=1.02,
        )
        fig.tight_layout()

        out_path = os.path.join(args.out_dir, f"{args.prefix}_{title_name}.png")
        fig.savefig(out_path, dpi=180, bbox_inches="tight")
        plt.close(fig)

        generated += 1
        print(f"Wrote {out_path}")

    if generated == 0:
        raise SystemExit("No plots generated. Check input files.")

    print(f"Done. generated={generated} skipped={skipped}")


if __name__ == "__main__":
    main()
