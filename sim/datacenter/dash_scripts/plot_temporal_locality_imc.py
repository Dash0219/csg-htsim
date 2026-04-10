#!/usr/bin/env python3
"""
Temporal-locality plotting helper for IMC cache-input INT logs.

This is a convenience wrapper around plot_temporal_locality.py with IMC defaults.
"""

import argparse
import os

from plot_temporal_locality import (
    assign_compact_lanes,
    build_concurrency_step,
    build_intervals,
    parse_int_records,
    sanitize_name,
)

import matplotlib.pyplot as plt


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("logfiles", nargs="*", help="IMC INT log file(s)")
    ap.add_argument(
        "--imc-defaults",
        action="store_true",
        help="Include built-in IMC defaults (also used when no logfile is provided)",
    )
    ap.add_argument("--out-dir", default="dash_results/imc/univ2/temporal_locality/plots", help="Output directory for PNGs")
    ap.add_argument("--prefix", default="temporal_locality_imc", help="Output filename prefix")
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
        "--with-concurrency",
        action="store_true",
        help="Overlay a concurrency (active intervals) step curve",
    )
    ap.add_argument(
        "--plot-concurrency",
        action="store_true",
        help="Also emit a dedicated concurrency-vs-time plot per input",
    )
    return ap.parse_args()


def default_imc_logs():
    files = []
    for ds in ("univ1", "univ2"):
        split_dir = os.path.join("dash_dataset", "imc", ds, f"{ds}_sinks_top8_prefix16")
        if not os.path.isdir(split_dir):
            continue
        for name in os.listdir(split_dir):
            if name.endswith(".txt") or name.endswith(".log"):
                files.append(os.path.join(split_dir, name))
    files.sort()
    return files


def main():
    args = parse_args()
    split_gap_ps = int(args.split_gap_us * 1_000_000)

    logfiles = list(args.logfiles)
    if args.imc_defaults or not logfiles:
        logfiles.extend(default_imc_logs())

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
        intervals = build_intervals(records, split_gap_ps=split_gap_ps, max_records=args.max_records)

        if not intervals:
            print(f"Skipping empty/non-parseable input: {logfile}")
            skipped += 1
            continue

        intervals.sort(key=lambda x: (x[1], x[2]))
        if args.max_intervals:
            intervals = intervals[: args.max_intervals]

        assigned, lanes = assign_compact_lanes(intervals)

        min_ts = min(s for _, s, _, _ in assigned)
        max_ts = max(e for _, _, e, _ in assigned)

        fig_h = max(4.0, min(14.0, 1.2 + lanes * 0.22))
        fig, ax = plt.subplots(figsize=(14, fig_h))

        cmap = plt.get_cmap("tab20")
        for flow, start, end, lane in assigned:
            start_us = (start - min_ts) / 1_000_000.0
            dur_us = max((end - start) / 1_000_000.0, 0.01)
            color = cmap(flow % 20)
            ax.broken_barh([(start_us, dur_us)], (lane - 0.4, 0.8), facecolors=color, alpha=0.85)

        span_us = (max_ts - min_ts) / 1_000_000.0
        ax.set_xlim(0, max(span_us, 1.0))
        ax.set_ylim(-1, lanes)
        ax.set_xlabel("time since first event (us)")
        ax.set_ylabel("compact activity lane")
        title_name = sanitize_name(logfile)
        ax.set_title(f"Temporal locality IMC ({title_name}): intervals={len(assigned)}, lanes={lanes}")
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
            axc.set_title(f"Concurrency vs time IMC ({title_name})")
            axc.grid(True, alpha=0.3)
            plt.tight_layout()
            c_out = os.path.join(args.out_dir, f"{args.prefix}_{title_name}_concurrency.png")
            plt.savefig(c_out, dpi=180)
            plt.close(fig2)
            print(f"Wrote {c_out}")

        generated += 1
        print(f"Wrote {out_path}")
        print(f"  intervals={len(assigned)} lanes={lanes} span_us={span_us:.3f}")

    if generated == 0:
        raise SystemExit("No plots generated. Check input files.")
    print(f"Done. generated={generated} skipped={skipped}")


if __name__ == "__main__":
    main()
