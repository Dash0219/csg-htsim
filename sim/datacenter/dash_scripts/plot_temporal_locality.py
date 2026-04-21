#!/usr/bin/env python3
"""
Compact temporal-locality plot for INT traces.

Produces a timeline where:
- X axis is time,
- Y axis is compact lanes (not flow IDs),
- each horizontal bar is a flow-active interval.

Lane packing is done greedily to minimize height; resulting height approximates
peak concurrency of the modeled intervals.
"""

import argparse
import heapq
import os
import re
from collections import defaultdict

import matplotlib.pyplot as plt

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


def collect_intervals_and_stats(records, split_gap_ps=0, max_records=0):
    """Build intervals and per-flow packet stats in one streaming pass."""
    flow_state = {}
    intervals = []

    count = 0
    for r in records:
        if max_records and count >= max_records:
            break
        count += 1
        if not r["ts"]:
            continue

        flow = r["flow"]
        ts = r["ts"][-1]
        if flow not in flow_state:
            flow_state[flow] = [ts, ts, 1]
            continue

        start, prev, pkt_count = flow_state[flow]
        if split_gap_ps > 0 and (ts - prev) > split_gap_ps:
            intervals.append((flow, start, prev))
            start = ts
        flow_state[flow] = [start, ts, pkt_count + 1]

    for flow, (start, prev, _) in flow_state.items():
        intervals.append((flow, start, prev))

    packet_flows = len(flow_state)
    single_packet_flows = sum(1 for _, _, pkt_count in flow_state.values() if pkt_count == 1)
    return intervals, packet_flows, single_packet_flows


def build_concurrency_step(intervals, min_ts, max_ts):
    """Build step-plot coordinates for active-interval concurrency over time."""
    if not intervals:
        return [], []

    events = []
    for _, start, end in intervals:
        events.append((start, 1))
        # End is inclusive for the interval bars; make decrement happen after end.
        events.append((end + 1, -1))

    events.sort(key=lambda x: (x[0], -x[1]))

    x = [0.0]
    y = [0]
    active = 0
    i = 0
    n = len(events)

    while i < n:
        t = events[i][0]
        delta = 0
        while i < n and events[i][0] == t:
            delta += events[i][1]
            i += 1
        active += delta
        x.append(max(0.0, (t - min_ts) / 1_000_000.0))
        y.append(active)

    x.append(max(0.0, (max_ts - min_ts) / 1_000_000.0))
    y.append(y[-1] if y else 0)
    return x, y


def assign_compact_lanes(intervals):
    """Assign intervals to minimum number of non-overlapping lanes."""
    intervals_sorted = sorted(intervals, key=lambda x: (x[1], x[2]))

    active = []
    free_lanes = []
    next_lane = 0

    assigned = []
    for flow, start, end in intervals_sorted:
        # Reclaim lanes whose last interval ended before (or at) this start.
        while active and active[0][0] <= start:
            _, lane_id = heapq.heappop(active)
            heapq.heappush(free_lanes, lane_id)

        if free_lanes:
            lane = heapq.heappop(free_lanes)
        else:
            lane = next_lane
            next_lane += 1

        heapq.heappush(active, (end, lane))
        assigned.append((flow, start, end, lane))

    return assigned, next_lane


def parse_args():
    ap = argparse.ArgumentParser(
        description="Plot temporal locality timelines from INT logs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("logfiles", nargs="*", help="INT log file(s)")
    ap.add_argument(
        "-d",
        "--dataset",
        action="append",
        default=[],
        help="Synthetic dataset name to plot (repeatable, e.g., -d a2a_pareto -d a2a_pareto_low_temp_locality)",
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
        "--out-dir",
        default="dash_results/synthetic/temporal_locality/plots",
        help="Output directory for PNGs",
    )
    ap.add_argument(
        "--logs-dir",
        default="dash_dataset/synthetic",
        help="Directory containing synthetic log_<dataset>.txt files",
    )
    ap.add_argument("--prefix", default="temporal_locality", help="Output filename prefix")
    ap.add_argument("--max-records", type=int, default=0, help="Only use first N records (0 means all)")
    ap.add_argument(
        "--split-gap-us",
        type=float,
        default=0.0,
        help="Split a flow into a new interval when idle gap exceeds this many microseconds",
    )
    ap.add_argument(
        "--max-intervals",
        type=int,
        default=0,
        help="Plot only first N intervals after sorting by start time (0 means all)",
    )
    ap.add_argument(
        "--max-plot-intervals",
        type=int,
        default=300000,
        help="Cap rendered intervals for performance (0 means no cap)",
    )
    ap.add_argument(
        "--with-concurrency",
        action="store_true",
        help="Overlay a concurrency (active intervals) step curve on temporal locality bars",
    )
    ap.add_argument(
        "--plot-concurrency",
        action="store_true",
        help="Also emit a dedicated concurrency-vs-time plot per input",
    )
    return ap.parse_args()


def default_synthetic_logs(logs_dir):
    return [synthetic_log_path(n, logs_dir) for n in synthetic_dataset_names(include_low_temp=False)]


def sanitize_name(path):
    base = os.path.splitext(os.path.basename(path))[0]
    if base.startswith("log_"):
        base = base[4:]
    return base


def main():
    args = parse_args()
    split_gap_ps = int(args.split_gap_us * 1_000_000)

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
        if args.synthetic_defaults or args.dataset:
            print("Note: explicit logfile(s) provided; ignoring --synthetic-defaults/--dataset selectors.")
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
    generated = 0
    skipped = 0

    for logfile in logfiles:
        if not os.path.exists(logfile):
            print(f"Skipping missing input: {logfile}")
            skipped += 1
            continue

        records = parse_int_records(logfile)
        intervals, packet_flows, single_packet_flows = collect_intervals_and_stats(
            records,
            split_gap_ps=split_gap_ps,
            max_records=args.max_records,
        )

        if not intervals:
            print(f"Skipping empty/non-parseable input: {logfile}")
            skipped += 1
            continue

        intervals.sort(key=lambda x: (x[1], x[2]))
        if args.max_intervals:
            intervals = intervals[: args.max_intervals]
        if args.max_plot_intervals and len(intervals) > args.max_plot_intervals:
            intervals = intervals[: args.max_plot_intervals]

        assigned, lanes = assign_compact_lanes(intervals)

        min_ts = min(s for _, s, _, _ in assigned)
        max_ts = max(e for _, _, e, _ in assigned)

        fig_h = max(4.0, min(14.0, 1.2 + lanes * 0.22))
        fig, ax = plt.subplots(figsize=(14, fig_h))

        lane_segments = defaultdict(list)
        for _, start, end, lane in assigned:
            start_us = (start - min_ts) / 1_000_000.0
            dur_us = max((end - start) / 1_000_000.0, 0.01)
            lane_segments[lane].append((start_us, dur_us))

        cmap = plt.get_cmap("tab20")
        for lane, segs in lane_segments.items():
            ax.broken_barh(segs, (lane - 0.4, 0.8), facecolors=cmap(lane % 20), alpha=0.85)

        span_us = (max_ts - min_ts) / 1_000_000.0
        ax.set_xlim(0, max(span_us, 1.0))
        ax.set_ylim(-1, lanes)
        ax.set_xlabel("time since first event (us)")
        ax.set_ylabel("compact activity lane")
        title_name = sanitize_name(logfile)
        ax.set_title(f"Temporal locality ({title_name}): intervals={len(assigned)}, lanes={lanes}")
        ax.grid(True, axis="x", alpha=0.3)

        x_step, y_step = build_concurrency_step(intervals, min_ts=min_ts, max_ts=max_ts)
        if args.with_concurrency and x_step:
            ax2 = ax.twinx()
            ax2.step(x_step, y_step, where="post", color="black", linewidth=1.4, alpha=0.85)
            ax2.set_ylabel("concurrent active flows")

        plt.tight_layout()
        out_path = os.path.join(args.out_dir, f"{args.prefix}_{title_name}.png")
        plt.savefig(out_path, dpi=180)
        plt.close(fig)

        if args.plot_concurrency and x_step:
            fig2, axc = plt.subplots(figsize=(14, 4.5))
            axc.step(x_step, y_step, where="post", color="#1f77b4", linewidth=1.8)
            axc.set_xlabel("time since first event (us)")
            axc.set_ylabel("concurrent active flows")
            axc.set_title(f"Concurrency vs time ({title_name})")
            axc.grid(True, alpha=0.3)
            plt.tight_layout()
            c_out = os.path.join(args.out_dir, f"{args.prefix}_{title_name}_concurrency.png")
            plt.savefig(c_out, dpi=180)
            plt.close(fig2)
            print(f"Wrote {c_out}")

        generated += 1
        print(f"Wrote {out_path}")
        pct_single = (100.0 * single_packet_flows / packet_flows) if packet_flows else 0.0
        peak_concurrency = max(y_step) if y_step else 0
        print(f"  intervals={len(assigned)} lanes={lanes} span_us={span_us:.3f}")
        print(
            f"  unique_flows={packet_flows} single_packet_flows={single_packet_flows} "
            f"single_packet_pct={pct_single:.2f}% peak_concurrency={peak_concurrency}"
        )

    if generated == 0:
        raise SystemExit("No plots generated. Check input files.")
    print(f"Done. generated={generated} skipped={skipped}")


if __name__ == "__main__":
    main()
