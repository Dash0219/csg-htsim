"""
flow_stats.py - analyze per-flow record counts and path-change rates in INT logs.

Usage:
  python3 fyp/dash_scripts/flow_stats.py <logfile> [<logfile> ...] [--top N] [--csv FILE] [--hist]
    python3 fyp/dash_scripts/flow_stats.py --use-defaults [--top 10]

Outputs per-flow statistics and an optional histogram of records-per-flow.
"""

import argparse
import csv
import os
import re
import sys
from collections import defaultdict


LOW_TEMP_SUFFIX = "low_temp_locality"


def default_synthetic_logs(include_low_temp=False):
    base = [
        "fyp/dash_dataset/synthetic/log_incast_mono.txt",
        "fyp/dash_dataset/synthetic/log_a2a_mono.txt",
        "fyp/dash_dataset/synthetic/log_incast_bimodal.txt",
        "fyp/dash_dataset/synthetic/log_a2a_bimodal.txt",
        "fyp/dash_dataset/synthetic/log_incast_pareto.txt",
        "fyp/dash_dataset/synthetic/log_a2a_pareto.txt",
        "fyp/dash_dataset/synthetic/log_incast_heavytail.txt",
        "fyp/dash_dataset/synthetic/log_a2a_heavytail.txt",
        "fyp/dash_dataset/synthetic/log_incast_exponential_skewed.txt",
        "fyp/dash_dataset/synthetic/log_a2a_exponential_skewed.txt",
    ]
    if include_low_temp:
        return [p.replace(".txt", f"_{LOW_TEMP_SUFFIX}.txt") for p in base]
    return base


def dataset_name_from_logpath(path):
    base = os.path.basename(path)
    if base.startswith("log_") and base.endswith(".txt"):
        return base[4:-4]
    return ""


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


def parse(path):
    """Parse INT packets from either multi-line or one-line tokenized logs."""
    token_re = re.compile(
        r"INT flow=(?P<flow>\d+) seq=(?P<seq>\d+) hops=(?P<hops>\d+)"
        r"|\[(?P<idx>\d+)\] sw=(?P<sw>\d+) type=(?P<typ>\d+) qs=(?P<qs>\d+) ts=(?P<ts>\d+) txbytes=(?P<txbytes>\d+) pktid=(?P<pktid>\d+)"
    )

    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()

    current = None
    for m in token_re.finditer(text):
        if m.group("flow") is not None:
            if current is not None:
                yield current
            current = {
                "flow": int(m.group("flow")),
                "seq": int(m.group("seq")),
                "hops": int(m.group("hops")),
                "sw": [],
                "ts": [],
            }
            continue

        if current is None:
            continue

        current["sw"].append(int(m.group("sw")))
        current["ts"].append(int(m.group("ts")))

    if current is not None:
        yield current


def compute_peak_concurrency(flow_windows):
    """Compute approximate concurrency from [first_ts, last_ts] flow windows."""
    if not flow_windows:
        return None

    events = []
    for start_ts, end_ts in flow_windows.values():
        events.append((start_ts, 1))
        events.append((end_ts, -1))

    events.sort(key=lambda x: (x[0], -x[1]))

    current = 0
    peak = 0
    peak_ts = events[0][0]
    area = 0
    prev_ts = events[0][0]

    for ts, delta in events:
        dt = ts - prev_ts
        if dt > 0:
            area += current * dt
        current += delta
        if current > peak:
            peak = current
            peak_ts = ts
        prev_ts = ts

    span = events[-1][0] - events[0][0]
    avg = (area / span) if span > 0 else float(peak)
    return {
        "peak": peak,
        "peak_ts": peak_ts,
        "avg": avg,
        "start_ts": events[0][0],
        "end_ts": events[-1][0],
        "span_ps": span,
    }


def analyse(logfile, max_records=0):
    counts = defaultdict(int)        # flow -> total INT records seen
    path_changes = defaultdict(int)  # flow -> number of path changes
    last_path = {}                   # flow -> last path tuple
    flow_windows = {}                # flow -> (first_ts, last_ts)

    seen = 0
    for rec in parse(logfile):
        if max_records and seen >= max_records:
            break
        seen += 1
        flow = rec["flow"]
        path = tuple(rec["sw"])
        ts_list = rec.get("ts", [])
        ts = ts_list[-1] if ts_list else None
        counts[flow] += 1
        if flow in last_path and last_path[flow] != path:
            path_changes[flow] += 1
        last_path[flow] = path

        if ts is not None:
            if flow not in flow_windows:
                flow_windows[flow] = (ts, ts)
            else:
                start_ts, end_ts = flow_windows[flow]
                flow_windows[flow] = (start_ts, ts if ts > end_ts else end_ts)

    stats = []
    for flow, count in counts.items():
        changes = path_changes.get(flow, 0)
        stability = 1.0 - (changes / count) if count > 0 else 1.0
        stats.append(
            {
                "flow": flow,
                "records": count,
                "path_changes": changes,
                "stability": round(stability, 4),
            }
        )

    stats.sort(key=lambda x: x["records"], reverse=True)
    conc = compute_peak_concurrency(flow_windows)
    return stats, set(counts.keys()), conc


def histogram(stats, buckets=None):
    if buckets is None:
        buckets = [1, 2, 5, 10, 50, 100, 500, 1000, 5000, 10000, float("inf")]

    labels = []
    counts = []
    for i in range(len(buckets) - 1):
        lo, hi = buckets[i], buckets[i + 1]
        label = f"[{lo}, {int(hi)})" if hi != float("inf") else f"[{lo}, inf)"
        count = sum(1 for s in stats if lo <= s["records"] < hi)
        labels.append(label)
        counts.append(count)

    max_count = max(counts) if counts else 1
    bar_width = 40
    print(f"\n{'Records/flow':<18}  {'#flows':>7}  {'bar'}")
    print("-" * 70)
    for label, count in zip(labels, counts):
        bar = "#" * int(bar_width * count / max_count)
        print(f"  {label:<16}  {count:>7,}  {bar}")


def summarize_stats(stats):
    total_flows = len(stats)
    total_records = sum(s["records"] for s in stats)
    one_shot = sum(1 for s in stats if s["records"] == 1)
    two_or_fewer = sum(1 for s in stats if s["records"] <= 2)
    mean_records = total_records / total_flows if total_flows else 0.0
    median_records = stats[total_flows // 2]["records"] if stats else 0

    return {
        "total_flows": total_flows,
        "total_records": total_records,
        "one_shot": one_shot,
        "two_or_fewer": two_or_fewer,
        "mean_records": mean_records,
        "median_records": median_records,
    }


def pct(num, den):
    return (100.0 * num / den) if den else 0.0


def main():
    ap = argparse.ArgumentParser(
        description="Analyze per-flow record counts and path-change rates in INT logs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("logfiles", nargs="*")
    ap.add_argument(
        "--use-defaults",
        action="store_true",
        help="Analyze built-in synthetic logs under fyp/dash_dataset/synthetic",
    )
    ap.add_argument(
        "--synthetic-defaults",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    ap.add_argument(
        "-d",
        "--dataset",
        action="append",
        default=[],
        help="Synthetic dataset name to analyze (repeatable)",
    )
    ap.add_argument(
        "-l",
        "--low-temp-locality",
        action="store_true",
        help="Use low-temp-locality synthetic datasets",
    )
    ap.add_argument("--top", type=int, default=20, help="Show top N flows by record count")
    ap.add_argument(
        "--max-records",
        type=int,
        default=0,
        help="Only analyze the first N parsed records per logfile (0 means all)",
    )
    ap.add_argument(
        "--concurrency",
        action="store_true",
        help="Estimate flow concurrency using per-flow first/last packet timestamps",
    )
    ap.add_argument("--csv", metavar="FILE", help="Write per-flow stats to CSV")
    ap.add_argument("--hist", action="store_true", help="Print histogram of records/flow")
    args = ap.parse_args()

    logfiles = list(args.logfiles)
    if args.dataset:
        defaults = default_synthetic_logs(include_low_temp=args.low_temp_locality)
        mapping = {dataset_name_from_logpath(p): p for p in defaults}
        wanted = []
        for d in args.dataset:
            d = normalize_dataset_alias(d)
            if args.low_temp_locality and not d.endswith(f"_{LOW_TEMP_SUFFIX}"):
                wanted.append(f"{d}_{LOW_TEMP_SUFFIX}")
            else:
                wanted.append(d)
        unknown = [d for d in wanted if d not in mapping]
        if unknown:
            ap.error(f"unknown dataset name(s): {', '.join(unknown)}")
        logfiles.extend(mapping[d] for d in wanted)
    elif args.use_defaults or args.synthetic_defaults or not logfiles:
        logfiles.extend(default_synthetic_logs(include_low_temp=args.low_temp_locality))
    if not logfiles:
        ap.error("no input logfiles selected")

    deduped = []
    seen = set()
    for lf in logfiles:
        if lf in seen:
            continue
        seen.add(lf)
        deduped.append(lf)
    logfiles = deduped

    existing = []
    for lf in logfiles:
        if not os.path.exists(lf):
            print(f"Skipping missing logfile: {lf}", file=sys.stderr)
            continue
        existing.append(lf)
    logfiles = existing
    if not logfiles:
        ap.error("no existing logfiles to analyze")

    if len(logfiles) > 1:
        print("=== Per-log summary ===")

    total_records_all = 0
    total_unique_flow_keys = 0
    unique_flow_ids_raw = set()
    max_peak_concurrency = 0
    single_log_conc = None
    all_rows = []

    for logfile in logfiles:
        print(f"Parsing {logfile} ...", file=sys.stderr)
        stats, flow_ids, conc = analyse(logfile, max_records=args.max_records)
        summary = summarize_stats(stats)

        if len(logfiles) > 1:
            print(f"\n[{logfile}]")
            print(f"  Unique flows:         {summary['total_flows']:>10,}")
            print(f"  Total records:        {summary['total_records']:>10,}")
            print(f"  Mean records/flow:    {summary['mean_records']:>10.1f}")
            print(f"  Median records/flow:  {summary['median_records']:>10,}")
            if args.concurrency:
                if conc is None:
                    print("  Peak concurrency:              n/a")
                else:
                    print(f"  Peak concurrency:      {conc['peak']:>10,}")
                    print(f"  Avg concurrency:       {conc['avg']:>10.2f}")

        total_records_all += summary["total_records"]
        total_unique_flow_keys += summary["total_flows"]
        unique_flow_ids_raw.update(flow_ids)
        if conc is not None:
            max_peak_concurrency = max(max_peak_concurrency, conc["peak"])
            if len(logfiles) == 1:
                single_log_conc = conc

        for row in stats:
            out = dict(row)
            if len(logfiles) > 1:
                out["logfile"] = logfile
            all_rows.append(out)

    stats = sorted(all_rows, key=lambda x: x["records"], reverse=True)
    summary = summarize_stats(stats)

    print("\n=== Summary ===")
    suffix = " (summed across logs)" if len(logfiles) > 1 else ""
    print(f"  Unique flows:         {summary['total_flows']:>10,}{suffix}")
    print(f"  Total records:        {summary['total_records']:>10,}")
    print(f"  Mean records/flow:    {summary['mean_records']:>10.1f}")
    print(f"  Median records/flow:  {summary['median_records']:>10,}")
    print(
        f"  One-shot flows (n=1): {summary['one_shot']:>10,}  "
        f"({pct(summary['one_shot'], summary['total_flows']):.1f}% of flows)"
    )
    print(
        f"  Flows with n<=2:      {summary['two_or_fewer']:>10,}  "
        f"({pct(summary['two_or_fewer'], summary['total_flows']):.1f}% of flows)"
    )
    print(f"  Flows with n>=100:    {sum(1 for s in stats if s['records'] >= 100):>10,}")
    if args.concurrency and len(logfiles) == 1:
        conc = single_log_conc
        if conc is None:
            print("  Peak concurrency:              n/a")
        else:
            print(f"  Peak concurrency:      {conc['peak']:>10,}")
            print(f"  Avg concurrency:       {conc['avg']:>10.2f}")
            print(f"  Time span (ps):        {conc['span_ps']:>10,}")

    if len(logfiles) > 1:
        print(f"  Total records (all logs):            {total_records_all:>10,}")
        print(f"  Total unique flow keys (log,flow):   {total_unique_flow_keys:>10,}")
        print(f"  Raw unique flow IDs across logs:     {len(unique_flow_ids_raw):>10,}")
        if args.concurrency:
            print(f"  Max peak concurrency (any log):      {max_peak_concurrency:>10,}")

    one_shot_records = sum(s["records"] for s in stats if s["records"] == 1)
    print(
        f"\n  One-shot flows account for {one_shot_records:,} records "
        f"({pct(one_shot_records, summary['total_records']):.1f}% of all records)"
    )

    print(f"\n=== Top {args.top} flows by record count ===")
    if not stats:
        print("  No flows parsed from input log(s).")
        if args.csv:
            fieldnames = ["flow", "records", "path_changes", "stability"]
            if len(logfiles) > 1:
                fieldnames = ["logfile"] + fieldnames
            with open(args.csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
            print(f"\nPer-flow CSV written to {args.csv}")
        return

    if len(logfiles) > 1:
        print(f"  {'logfile':<44}  {'flow':>8}  {'records':>10}  {'path_changes':>13}  {'stability':>10}")
        print(f"  {'-' * 44}  {'-' * 8}  {'-' * 10}  {'-' * 13}  {'-' * 10}")
        for row in stats[: args.top]:
            print(
                f"  {row['logfile']:<44}  {row['flow']:>8}  {row['records']:>10,}  "
                f"{row['path_changes']:>13,}  {row['stability']:>10.3f}"
            )
    else:
        print(f"  {'flow':>8}  {'records':>10}  {'path_changes':>13}  {'stability':>10}")
        print(f"  {'-' * 8}  {'-' * 10}  {'-' * 13}  {'-' * 10}")
        for row in stats[: args.top]:
            print(
                f"  {row['flow']:>8}  {row['records']:>10,}  "
                f"{row['path_changes']:>13,}  {row['stability']:>10.3f}"
            )

    if args.hist:
        histogram(stats)

    if args.csv:
        fieldnames = ["flow", "records", "path_changes", "stability"]
        if len(logfiles) > 1:
            fieldnames = ["logfile"] + fieldnames
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(stats)
        print(f"\nPer-flow CSV written to {args.csv}")


if __name__ == "__main__":
    main()
