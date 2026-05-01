#!/usr/bin/env python3
"""Plot TTL-window (inter-arrival gap) distributions from INT logs."""

import argparse
import os
from typing import Iterable, List, Sequence, Tuple

LOW_TEMP_SUFFIX = "low_temp_locality"


def synthetic_dataset_names(include_low_temp=False):
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


def synthetic_log_path(dataset_name, logs_dir="fyp/dash_dataset/synthetic"):
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


def sanitize_name(path):
    base = os.path.splitext(os.path.basename(path))[0]
    if base.startswith("log_"):
        base = base[4:]
    return base


def percentile(sorted_vals: Sequence[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    if p <= 0.0:
        return sorted_vals[0]
    if p >= 1.0:
        return sorted_vals[-1]
    idx = int((len(sorted_vals) - 1) * p)
    return sorted_vals[idx]


def parse_ttl_grid(raw: str) -> List[float]:
    vals = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        v = float(part)
        if v <= 0:
            continue
        vals.append(v)
    dedup = sorted(set(vals))
    return dedup


def event_points_from_record(rec, key_level: str, event_mode: str, qs_threshold: int) -> List[Tuple[str, int]]:
    flow = int(rec["flow"])
    sw = rec.get("sw", [])
    typ = rec.get("typ", [])
    qs = rec.get("qs", [])
    ts = rec.get("ts", [])

    if not ts:
        return []

    points: List[Tuple[str, int]] = []

    if key_level == "switch":
        max_len = min(len(sw), len(typ), len(qs), len(ts))
        seen = {}
        for i in range(max_len):
            if event_mode == "congestion" and qs[i] < qs_threshold:
                continue
            key = f"{sw[i]}:{typ[i]}"
            prev_ts = seen.get(key)
            if prev_ts is None or ts[i] > prev_ts:
                seen[key] = int(ts[i])
        for k, v in seen.items():
            points.append((k, v))
        return points

    chosen_ts = int(ts[-1])
    if event_mode == "congestion":
        max_len = min(len(qs), len(ts))
        congested_idx = [i for i in range(max_len) if qs[i] >= qs_threshold]
        if not congested_idx:
            return []
        chosen_ts = int(ts[congested_idx[-1]])

    if key_level == "source":
        source = str(sw[0]) if sw else f"flow_{flow}"
        return [(f"src:{source}", chosen_ts)]

    return [(f"flow:{flow}", chosen_ts)]


def collect_gaps_us(
    logfiles: Iterable[str],
    key_level: str,
    event_mode: str,
    qs_threshold: int,
    max_records: int,
):
    try:
        from fyp.dash_scripts.cache_sim import parse
    except ModuleNotFoundError:
        from cache_sim import parse  # type: ignore

    gaps_us: List[float] = []
    unique_keys = set()
    parsed_records = 0
    total_events = 0

    for logfile in logfiles:
        per_file_records = 0
        last_ts = {}

        for rec in parse(logfile):
            if max_records > 0 and parsed_records >= max_records:
                break
            parsed_records += 1
            per_file_records += 1

            for key, ts in event_points_from_record(rec, key_level, event_mode, qs_threshold):
                unique_keys.add(key)
                total_events += 1
                prev = last_ts.get(key)
                if prev is not None and ts > prev:
                    gaps_us.append((ts - prev) / 1_000_000.0)
                if prev is None or ts > prev:
                    last_ts[key] = ts

        if max_records > 0 and parsed_records >= max_records:
            break

    gaps_us.sort()
    return gaps_us, parsed_records, total_events, len(unique_keys)


def parse_args():
    ap = argparse.ArgumentParser(
        description="Plot TTL-window (inter-arrival gap) distributions from INT logs.",
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
        default="fyp/dash_dataset/synthetic",
        help="Directory containing synthetic log_<dataset>.txt files",
    )
    ap.add_argument(
        "--out-dir",
        default="fyp/dash_results/synthetic/ttl_window/plots",
        help="Output directory for PNG/text/csv outputs",
    )
    ap.add_argument("--prefix", default="ttl_window", help="Output filename prefix")
    ap.add_argument("--max-records", type=int, default=0, help="Only use first N records across all inputs (0 means all)")
    ap.add_argument("--bins", type=int, default=50, help="Histogram bin count")
    ap.add_argument(
        "--key-level",
        choices=["flow", "source", "switch"],
        default="flow",
        help="Key granularity for TTL gap modeling",
    )
    ap.add_argument(
        "--event-mode",
        choices=["all", "congestion"],
        default="all",
        help="Whether to use all observations or only congestion-qualified observations",
    )
    ap.add_argument("--qs-threshold", type=int, default=50000, help="Queue threshold (bytes) for --event-mode congestion")
    ap.add_argument(
        "--ttl-grid-us",
        default="10,50,100,250,500,1000,2500,5000,10000,25000,50000,100000,250000,500000,1000000",
        help="Comma-separated TTL candidates (microseconds) for cache-window hit coverage",
    )
    ap.add_argument("--merge-inputs", action="store_true", help="Merge all selected logfiles into a single aggregate output")
    ap.add_argument("--merge-label", default="", help="Output label when --merge-inputs is set")
    return ap.parse_args()


def main():
    args = parse_args()
    ttl_grid = parse_ttl_grid(args.ttl_grid_us)

    known_datasets = set(synthetic_dataset_names(include_low_temp=True))
    selected_datasets = []
    for d in args.dataset:
        d = normalize_dataset_alias(d)
        if args.low_temp_locality and not d.endswith(f"_{LOW_TEMP_SUFFIX}"):
            selected_datasets.append(f"{d}_{LOW_TEMP_SUFFIX}")
        else:
            selected_datasets.append(d)

    unknown = [d for d in selected_datasets if d not in known_datasets]
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
                logfiles.extend(
                    synthetic_log_path(n, args.logs_dir)
                    for n in synthetic_dataset_names(include_low_temp=True)
                    if n.endswith(f"_{LOW_TEMP_SUFFIX}")
                )
            elif args.include_low_temp_defaults:
                logfiles.extend(synthetic_log_path(n, args.logs_dir) for n in synthetic_dataset_names(include_low_temp=True))
            else:
                logfiles.extend(synthetic_log_path(n, args.logs_dir) for n in synthetic_dataset_names(include_low_temp=False))

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

    groups = []
    if args.merge_inputs:
        label = args.merge_label.strip() or "merged"
        groups.append((label, logfiles))
    else:
        for lf in logfiles:
            groups.append((sanitize_name(lf), [lf]))

    generated = 0
    skipped = 0

    for label, files in groups:
        missing = [f for f in files if not os.path.exists(f)]
        if missing:
            for m in missing:
                print(f"Skipping missing input: {m}")
            if len(missing) == len(files):
                skipped += 1
                continue
            files = [f for f in files if os.path.exists(f)]

        gaps_us, parsed_records, total_events, unique_keys = collect_gaps_us(
            files,
            key_level=args.key_level,
            event_mode=args.event_mode,
            qs_threshold=args.qs_threshold,
            max_records=args.max_records,
        )

        if not gaps_us:
            print(f"Skipping empty/non-parseable input group: {label}")
            skipped += 1
            continue

        p50 = percentile(gaps_us, 0.50)
        p90 = percentile(gaps_us, 0.90)
        p95 = percentile(gaps_us, 0.95)
        p99 = percentile(gaps_us, 0.99)
        max_gap = gaps_us[-1]

        fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(18.2, 4.8))

        hist_vals = [max(v, 1e-6) for v in gaps_us]
        ax1.hist(hist_vals, bins=max(10, args.bins), color="#1f77b4", alpha=0.85)
        ax1.set_xscale("log")
        ax1.set_xlabel("inter-arrival gap (us)")
        ax1.set_ylabel("# observations")
        ax1.set_title("TTL window histogram")
        ax1.grid(True, alpha=0.3)

        n = len(gaps_us)
        x = [max(v, 1e-6) for v in gaps_us]
        y = [1.0 - (i + 1) / n for i in range(n)]
        ax2.plot(x, y, color="#d62728", linewidth=1.7)
        ax2.set_xscale("log")
        ax2.set_yscale("log")
        ax2.set_xlabel("inter-arrival gap (us)")
        ax2.set_ylabel("CCDF")
        ax2.set_title("Gap tail (larger windows needed)")
        ax2.grid(True, which="both", alpha=0.3)

        coverages = []
        for ttl_us in ttl_grid:
            hits = 0
            for g in gaps_us:
                if g <= ttl_us:
                    hits += 1
            coverages.append((ttl_us, 100.0 * hits / len(gaps_us)))

        ax3.plot([c[0] for c in coverages], [c[1] for c in coverages], marker="o", color="#2ca02c", linewidth=1.7)
        ax3.set_xscale("log")
        ax3.set_ylim(0, 100)
        ax3.set_xlabel("TTL window (us)")
        ax3.set_ylabel("coverage: gap <= TTL (%)")
        ax3.set_title("TTL sensitivity curve")
        ax3.grid(True, which="both", alpha=0.3)

        fig.suptitle(
            (
                f"TTL window distribution ({label}) | key={args.key_level} mode={args.event_mode} "
                f"obs={len(gaps_us):,} p50={p50:.3f}us p90={p90:.3f}us p95={p95:.3f}us p99={p99:.3f}us max={max_gap:.3f}us"
            ),
            y=1.03,
        )
        fig.tight_layout()

        out_png = os.path.join(args.out_dir, f"{args.prefix}_{label}.png")
        fig.savefig(out_png, dpi=180, bbox_inches="tight")
        plt.close(fig)

        out_txt = os.path.join(args.out_dir, f"{args.prefix}_{label}_summary.txt")
        with open(out_txt, "w", encoding="utf-8") as f:
            f.write(f"label: {label}\n")
            f.write(f"key_level: {args.key_level}\n")
            f.write(f"event_mode: {args.event_mode}\n")
            f.write(f"qs_threshold: {args.qs_threshold}\n")
            f.write(f"inputs: {len(files)}\n")
            f.write(f"parsed_records: {parsed_records}\n")
            f.write(f"total_events: {total_events}\n")
            f.write(f"unique_keys: {unique_keys}\n")
            f.write(f"gaps_observations: {len(gaps_us)}\n")
            f.write(f"p50_us: {p50:.6f}\n")
            f.write(f"p90_us: {p90:.6f}\n")
            f.write(f"p95_us: {p95:.6f}\n")
            f.write(f"p99_us: {p99:.6f}\n")
            f.write(f"max_us: {max_gap:.6f}\n")
            f.write("\n")
            f.write("ttl_us,coverage_pct\n")
            for ttl_us, cov in coverages:
                f.write(f"{ttl_us:.6f},{cov:.6f}\n")

        out_csv = os.path.join(args.out_dir, f"{args.prefix}_{label}_coverage.csv")
        with open(out_csv, "w", encoding="utf-8") as f:
            f.write("ttl_us,coverage_pct\n")
            for ttl_us, cov in coverages:
                f.write(f"{ttl_us:.6f},{cov:.6f}\n")

        generated += 1
        print(f"Wrote {out_png}")
        print(f"Wrote {out_txt}")
        print(f"Wrote {out_csv}")

    if generated == 0:
        raise SystemExit("No plots generated. Check input files.")

    print(f"Done. generated={generated} skipped={skipped}")


if __name__ == "__main__":
    main()
