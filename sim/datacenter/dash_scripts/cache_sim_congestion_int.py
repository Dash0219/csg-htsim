"""
Congestion-event cache simulator for synthetic INT logs.

This is the third evaluation track alongside route-change and source-seen modes.
It extracts congestion events from INT hop queue sizes and reuses the same cache
policies/output schema as cache_sim.py.

Default behavior:
  - key-level: switch (switch_id, switch_type)
  - signature: seen (all anomalies for a key share one signature)
  - event condition: hop queue size >= --qs-threshold

Rationale:
  Congestion is fundamentally a per-resource (queue/link) condition, so the
  default key is per switch/type, not per flow. A flow-key mode is provided for
  comparison and attribution experiments.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple, cast

from cache_sim import (
    AdaptiveAdmissionLRU,
    AdmissionFilterLRU,
    CacheINTFreshnessLRU,
    CacheResult,
    FIFOLastPath,
    FlowLifetimeAdaptiveTTL,
    FreshnessInvalidationLRU,
    InfiniteLastPath,
    LFULastPath,
    LRULastPath,
    LRULastPathTTL,
    OnlineAdaptiveAdmissionLRU,
    PendingAdmissionLRU,
    PITCollapsedLRU,
    TinyCacheLRU,
    TinyLFULRU,
    TimingBloomLRU,
    parse,
    print_results,
    write_csv,
)
from cache_sim_source_seen import simulate_source, sweep, write_per_split_csvs


def resolve_inputs(input_path: Path, pattern: str) -> List[Path]:
    if input_path.is_file():
        return [input_path]
    if not input_path.is_dir():
        raise FileNotFoundError(f"Input path does not exist: {input_path}")
    files = sorted([p for p in input_path.glob(pattern) if p.is_file()], key=lambda p: p.name)
    if not files:
        raise FileNotFoundError(f"No matching files under {input_path} with pattern {pattern}")
    return files


def merge_results(dest: CacheResult, src: CacheResult) -> None:
    dest.total += src.total
    dest.hits += src.hits
    dest.necessary_forwards += src.necessary_forwards
    dest.new_route_forwards += src.new_route_forwards
    dest.route_change_forwards += src.route_change_forwards
    dest.redundant_forwards += src.redundant_forwards
    dest.evictions += src.evictions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_path", help="Synthetic INT logfile path or directory")
    parser.add_argument(
        "--pattern",
        default="*.txt",
        help="Glob when input_path is a directory (default: %(default)s)",
    )
    parser.add_argument("--max-records", type=int, default=0, help="Only parse first N INT packets (0 means all)")
    parser.add_argument(
        "--qs-threshold",
        type=int,
        default=50000,
        help="Queue-size threshold (bytes) to treat a hop as congested",
    )
    parser.add_argument(
        "--key-level",
        choices=["switch", "flow"],
        default="switch",
        help="Cache key granularity for congestion events",
    )
    parser.add_argument(
        "--signature",
        choices=["seen", "bucket"],
        default="seen",
        help=(
            "Event signature mode: 'seen' treats all anomalies for a key as same class; "
            "'bucket' tracks queue severity buckets"
        ),
    )
    parser.add_argument(
        "--bucket-bytes",
        type=int,
        default=8192,
        help="Queue-size bucket width when --signature bucket",
    )

    parser.add_argument("--sweep", action="store_true", help="Sweep all policies/sizes")
    parser.add_argument(
        "--cache",
        choices=[
            "lru",
            "lfu",
            "fifo",
            "admission",
            "pending_admission",
            "pit",
            "adaptive",
            "online_adaptive",
            "bloom",
            "tiny_cache",
            "tiny_lfu",
            "lru_ttl",
            "f_inv",
            "cache_int",
            "life_ttl",
            "infinite_lp",
        ],
        default="lru",
        help="Cache policy for single run",
    )
    parser.add_argument("--size", type=int, default=64, help="Cache capacity for single run")
    parser.add_argument(
        "--pending-reset-every",
        type=int,
        default=0,
        help="Periodically clear pending sketch every N records (0 disables)",
    )
    parser.add_argument("--bloom-bits", type=int, default=1 << 18, help="Bloom filter size in bits per filter")
    parser.add_argument("--bloom-hashes", type=int, default=4, help="Number of Bloom hash functions")
    parser.add_argument("--bloom-epoch-records", type=int, default=256, help="Rotate Bloom windows every N records")
    parser.add_argument("--ttl-ms", type=float, default=10.0, help="Keep-alive TTL in milliseconds for LRUTTL")
    parser.add_argument("--fresh-ttl-ms", type=float, default=2.0, help="Freshness TTL in milliseconds for FreshnessInvalidationLRU")
    parser.add_argument("--dual-dyn-ttl-ms", type=float, default=0.5, help="Dynamic-class TTL in milliseconds for CacheINTFreshnessLRU")
    parser.add_argument("--pit-download-us", type=float, default=2.0, help="PIT download delay in microseconds for PITCollapsedLRU")
    parser.add_argument("--dual-stable-hits", type=int, default=3, help="Stable hits needed to promote a flow to static class")
    parser.add_argument("--life-min-ttl-ms", type=float, default=0.1, help="Minimum per-flow TTL in milliseconds for FlowLifetimeAdaptiveTTL")
    parser.add_argument("--life-max-ttl-ms", type=float, default=20.0, help="Maximum per-flow TTL in milliseconds for FlowLifetimeAdaptiveTTL")
    parser.add_argument("--life-base-ttl-ms", type=float, default=0.5, help="Bootstrap TTL in milliseconds before flow lifetime is learned")
    parser.add_argument("--life-ema-alpha", type=float, default=0.2, help="EMA alpha for per-flow gap learning in FlowLifetimeAdaptiveTTL")
    parser.add_argument("--life-ttl-multiplier", type=float, default=4.0, help="Multiplier mapping learned inter-arrival gap to TTL in FlowLifetimeAdaptiveTTL")
    parser.add_argument("--csv", metavar="FILE", help="Write results to CSV")
    parser.add_argument(
        "--csv-per-split",
        action="store_true",
        help="When input_path is a directory, also write one CSV per matched split file (requires --csv).",
    )
    parser.add_argument(
        "--csv-splits-dir",
        default="",
        help="Directory for per-split CSV outputs. Default: sibling folder named <total_csv_stem>_splits next to --csv",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Use the optional fast source-seen simulation path if available",
    )
    parser.add_argument(
        "--quiet-table",
        action="store_true",
        help="Suppress printing the final sweep table to stdout",
    )
    return parser.parse_args()


def make_signature(qs: int, sw: int, stype: int, args: argparse.Namespace):
    if args.signature == "seen":
        return ("cong",)
    bucket = qs // max(1, args.bucket_bytes)
    if args.key_level == "switch":
        return (bucket,)
    return ((sw, stype, bucket),)


def build_congestion_records(logfile: Path, args: argparse.Namespace) -> List[Dict[str, object]]:
    records: List[Dict[str, object]] = []
    count = 0

    for rec in parse(str(logfile)):
        count += 1
        if args.max_records > 0 and count > args.max_records:
            break

        flow = int(cast(int, rec["flow"]))
        sw = cast(List[int], rec.get("sw", []))
        typ = cast(List[int], rec.get("typ", []))
        qs = cast(List[int], rec.get("qs", []))
        ts = cast(List[int], rec.get("ts", []))

        if not sw or not typ or not qs:
            continue

        if args.key_level == "switch":
            for i in range(min(len(sw), len(typ), len(qs), len(ts))):
                if qs[i] < args.qs_threshold:
                    continue
                source = f"{sw[i]}:{typ[i]}"
                route_sig = make_signature(qs[i], sw[i], typ[i], args)
                ts_ps = int(ts[i])
                records.append({"source": source, "route_sig": route_sig, "ts_ps": ts_ps})
        else:
            congested_idx = [i for i, v in enumerate(qs) if v >= args.qs_threshold]
            if not congested_idx:
                continue
            source = str(flow)
            if args.signature == "seen":
                route_sig = ("cong",)
            else:
                route_sig = tuple(
                    (sw[i], typ[i], qs[i] // max(1, args.bucket_bytes))
                    for i in congested_idx
                    if i < len(sw) and i < len(typ)
                )
                if not route_sig:
                    route_sig = ("cong",)
            ts_ps = int(ts[congested_idx[-1]]) if ts and congested_idx[-1] < len(ts) else 0
            records.append({"source": source, "route_sig": route_sig, "ts_ps": ts_ps})

    return records


def cache_factory_map(args: argparse.Namespace):
    ttl_ps = int(args.ttl_ms * 1_000_000_000)
    fresh_ttl_ps = int(args.fresh_ttl_ms * 1_000_000_000)
    dual_dyn_ttl_ps = int(args.dual_dyn_ttl_ms * 1_000_000_000)
    pit_download_ps = int(args.pit_download_us * 1_000_000)
    life_min_ttl_ps = int(args.life_min_ttl_ms * 1_000_000_000)
    life_max_ttl_ps = int(args.life_max_ttl_ms * 1_000_000_000)
    life_base_ttl_ps = int(args.life_base_ttl_ms * 1_000_000_000)

    return {
        "lru": lambda: LRULastPath(args.size),
        "lfu": lambda: LFULastPath(args.size),
        "fifo": lambda: FIFOLastPath(args.size),
        "admission": lambda: AdmissionFilterLRU(
            args.size,
            pending_reset_every=args.bloom_epoch_records,
            bloom_bits=args.bloom_bits,
            bloom_hashes=args.bloom_hashes,
        ),
        "pending_admission": lambda: PendingAdmissionLRU(args.size, pending_reset_every=args.pending_reset_every),
        "pit": lambda: PITCollapsedLRU(args.size, download_delay_ps=pit_download_ps),
        "adaptive": lambda: AdaptiveAdmissionLRU(args.size, pending_reset_every=args.pending_reset_every),
        "online_adaptive": lambda: OnlineAdaptiveAdmissionLRU(args.size),
        "bloom": lambda: TimingBloomLRU(args.size, args.bloom_bits, args.bloom_hashes, args.bloom_epoch_records),
        "tiny_cache": lambda: TinyCacheLRU(args.size),
        "tiny_lfu": lambda: TinyLFULRU(args.size),
        "lru_ttl": lambda: LRULastPathTTL(args.size, ttl_ps),
        "f_inv": lambda: FreshnessInvalidationLRU(args.size, fresh_ttl_ps),
        "cache_int": lambda: CacheINTFreshnessLRU(args.size, dual_dyn_ttl_ps, args.dual_stable_hits),
        "life_ttl": lambda: FlowLifetimeAdaptiveTTL(
            args.size,
            min_ttl_ps=life_min_ttl_ps,
            max_ttl_ps=life_max_ttl_ps,
            base_ttl_ps=life_base_ttl_ps,
            ema_alpha=args.life_ema_alpha,
            ttl_multiplier=args.life_ttl_multiplier,
        ),
        "infinite_lp": lambda: InfiniteLastPath(),
    }


def sweep_splitwise(files: Sequence[Path], args: argparse.Namespace) -> Tuple[List[CacheResult], List[Tuple[Path, List[CacheResult]]]]:
    by_key: Dict[Tuple[str, object], CacheResult] = {}
    order: List[Tuple[str, object]] = []
    split_outputs: List[Tuple[Path, List[CacheResult]]] = []

    for idx, path in enumerate(files, start=1):
        print(f"Loading split {idx}/{len(files)}: {path.name}", file=sys.stderr)
        records = build_congestion_records(path, args)
        print(f"  Loaded {len(records):,} congestion records", file=sys.stderr)
        split_results = sweep(records, use_fast=args.fast)
        split_outputs.append((path, split_results))
        for r in split_results:
            key = (r.cache_name, r.capacity)
            if key not in by_key:
                by_key[key] = CacheResult(cache_name=r.cache_name, capacity=r.capacity)
                order.append(key)
            merge_results(by_key[key], r)

    return [by_key[k] for k in order], split_outputs


def run_single_splitwise(files: Sequence[Path], cache_factory, unbounded: bool, args: argparse.Namespace) -> CacheResult:
    seed_cache = cache_factory()
    total_result = CacheResult(cache_name=seed_cache.name, capacity=seed_cache.capacity)

    for idx, path in enumerate(files, start=1):
        print(f"Loading split {idx}/{len(files)}: {path.name}", file=sys.stderr)
        records = build_congestion_records(path, args)
        print(f"  Loaded {len(records):,} congestion records", file=sys.stderr)

        split_cache = cache_factory()
        split_oracle = None if unbounded else InfiniteLastPath()
        split_result = simulate_source(records, split_cache, split_oracle, use_fast=args.fast)
        merge_results(total_result, split_result)

    return total_result


def main() -> None:
    args = parse_args()
    input_path = Path(args.input_path)
    files = resolve_inputs(input_path, args.pattern)
    splitwise = len(files) > 1

    records: List[Dict[str, object]] = []
    if splitwise:
        print(f"Processing {len(files)} split file(s) independently and aggregating results...", file=sys.stderr)
    else:
        records = build_congestion_records(files[0], args)
        print(f"Loaded {len(records):,} congestion records", file=sys.stderr)

    if args.sweep:
        split_outputs: List[Tuple[Path, List[CacheResult]]] = []
        if splitwise:
            results, split_outputs = sweep_splitwise(files, args)
        else:
            results = sweep(records, use_fast=args.fast)
        if not args.quiet_table:
            print_results(results)
        if args.csv:
            write_csv(results, args.csv)
            if splitwise and args.csv_per_split:
                write_per_split_csvs(split_outputs, args.csv, args.csv_splits_dir)
        elif args.csv_per_split:
            print("Ignoring --csv-per-split because --csv was not provided.", file=sys.stderr)
        return

    factories = cache_factory_map(args)
    unbounded = args.cache == "infinite_lp"
    if splitwise:
        result = run_single_splitwise(files, factories[args.cache], unbounded, args)
    else:
        cache = factories[args.cache]()
        oracle = None if unbounded else InfiniteLastPath()
        result = simulate_source(records, cache, oracle, use_fast=args.fast)
    print(result)


if __name__ == "__main__":
    main()
