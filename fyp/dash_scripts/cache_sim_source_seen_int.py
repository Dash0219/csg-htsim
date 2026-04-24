"""
Source-seen cache simulator for synthetic INT logs.

This variant mirrors cache_sim.py output schema while using source-keyed route
signatures, making it easy to compare against the normal flow-keyed model.

Input format:
  INT logs from htsim stderr (same files used by cache_sim.py).

Output format:
  Same CSV columns as cache_sim.py via cache_sim.write_csv.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple, cast

try:
    from fyp.dash_scripts.cache_sim import (
        AdaptiveAdmissionLRU,
        AdmissionFilterLRU,
        CacheINTFreshnessLRU,
        CacheResult,
        FIFOLastPath,
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
        write_capacity_csv,
    )
    from fyp.dash_scripts.cache_sim_source_seen import simulate_source, sweep
except ModuleNotFoundError:
    from cache_sim import (  # type: ignore
        AdaptiveAdmissionLRU,
        AdmissionFilterLRU,
        CacheINTFreshnessLRU,
        CacheResult,
        FIFOLastPath,
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
        write_capacity_csv,
    )
    from cache_sim_source_seen import simulate_source, sweep  # type: ignore


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
    parser.add_argument("--source-key", choices=["src_sw", "flow"], default="src_sw", help="How to derive source identity")
    parser.add_argument(
        "--route-key",
        choices=["seen", "path", "dst_sw"],
        default="seen",
        help=(
            "How to derive route signature: 'seen' is true source-seen mode "
            "(all packets for a source share one signature), while 'path' and 'dst_sw' "
            "retain route-sensitive behavior"
        ),
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
    parser.add_argument("--dual-dyn-ttl-ms", type=float, default=0.5, help="Dynamic-class TTL in milliseconds for DualFreshnessLRU")
    parser.add_argument("--dual-stable-hits", type=int, default=3, help="Stable hits needed to promote a flow to static class")
    parser.add_argument("--pit-download-us", type=float, default=2.0, help="PIT download delay in microseconds for PITCollapsedLRU")
    parser.add_argument("--csv", metavar="FILE", help="Write results to CSV")
    parser.add_argument(
        "--capacity-csv",
        metavar="FILE",
        help="Write cache pressure samples (occupancy over time) to CSV",
    )
    parser.add_argument(
        "--capacity-sample-every",
        type=int,
        default=1000,
        help="Record one capacity sample every N packets (default: %(default)s)",
    )
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


def build_source_records(
    logfile: Path, source_key: str, route_key: str, max_records: int
) -> List[Tuple[str, Tuple[object, ...], int]]:
    records: List[Tuple[str, Tuple[object, ...], int]] = []
    count = 0
    for rec in parse(str(logfile)):
        count += 1
        if max_records > 0 and count > max_records:
            break

        flow = int(cast(int, rec["flow"]))
        sw = cast(List[int], rec.get("sw", []))
        ts_list = cast(List[int], rec.get("ts", []))

        if source_key == "flow":
            source = str(flow)
        else:
            source = str(sw[0]) if sw else f"flow_{flow}"

        if route_key == "seen":
            # True source-seen semantics: once a source is admitted, later packets
            # from that source are suppressible unless the source entry is evicted.
            route_sig = ("seen",)
        elif route_key == "dst_sw":
            route_sig: Tuple[object, ...] = (sw[-1],) if sw else ("none",)
        else:
            route_sig = tuple(sw)

        ts_ps = int(ts_list[-1]) if ts_list else 0
        records.append((source, route_sig, ts_ps))

    return records


def sweep_splitwise(
    files: Sequence[Path],
    source_key: str,
    route_key: str,
    max_records: int,
    use_fast: bool = False,
    capacity_curves=None,
    capacity_sample_every: int = 1000,
) -> Tuple[List[CacheResult], List[Tuple[Path, List[CacheResult]]]]:
    by_key: Dict[Tuple[str, object], CacheResult] = {}
    order: List[Tuple[str, object]] = []
    split_outputs: List[Tuple[Path, List[CacheResult]]] = []
    record_offset = 0

    for idx, path in enumerate(files, start=1):
        print(f"Loading split {idx}/{len(files)}: {path.name}", file=sys.stderr)
        records = build_source_records(path, source_key, route_key, max_records)
        print(f"  Loaded {len(records):,} source records", file=sys.stderr)
        split_capacity_curves = {} if capacity_curves is not None else None
        split_results = sweep(
            records,
            use_fast=use_fast,
            capacity_curves=split_capacity_curves,
            capacity_sample_every=capacity_sample_every,
        )
        split_outputs.append((path, split_results))
        if capacity_curves is not None and split_capacity_curves is not None:
            for key, samples in split_capacity_curves.items():
                merged = capacity_curves.setdefault(key, [])
                for rec_idx, ts_ps, slots_used in samples:
                    merged.append((rec_idx + record_offset, ts_ps, slots_used))
        record_offset += len(records)
        for r in split_results:
            key = (r.cache_name, r.capacity)
            if key not in by_key:
                by_key[key] = CacheResult(cache_name=r.cache_name, capacity=r.capacity)
                order.append(key)
            merge_results(by_key[key], r)

    return [by_key[k] for k in order], split_outputs


def run_single_splitwise(
    files: Sequence[Path], cache_factory, unbounded: bool, source_key: str, route_key: str, max_records: int, use_fast: bool = False
) -> CacheResult:
    seed_cache = cache_factory()
    total_result = CacheResult(cache_name=seed_cache.name, capacity=seed_cache.capacity)

    for idx, path in enumerate(files, start=1):
        print(f"Loading split {idx}/{len(files)}: {path.name}", file=sys.stderr)
        records = build_source_records(path, source_key, route_key, max_records)
        print(f"  Loaded {len(records):,} source records", file=sys.stderr)

        split_cache = cache_factory()
        split_oracle = None if unbounded else InfiniteLastPath()
        split_result = simulate_source(records, split_cache, split_oracle, use_fast=use_fast)
        merge_results(total_result, split_result)

    return total_result


def run_single(records: List[Tuple[str, Tuple[object, ...], int]], args: argparse.Namespace) -> CacheResult:
    ttl_ps = int(args.ttl_ms * 1_000_000_000)
    fresh_ttl_ps = int(args.fresh_ttl_ms * 1_000_000_000)
    dual_dyn_ttl_ps = int(args.dual_dyn_ttl_ms * 1_000_000_000)
    pit_download_ps = int(args.pit_download_us * 1_000_000)

    cache_map = {
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
        "infinite_lp": lambda: InfiniteLastPath(),
    }

    unbounded = args.cache == "infinite_lp"
    cache = cache_map[args.cache]()
    oracle = None if unbounded else InfiniteLastPath()
    return simulate_source(records, cache, oracle, use_fast=args.fast)


def main() -> None:
    args = parse_args()
    input_path = Path(args.input_path)
    files = resolve_inputs(input_path, args.pattern)
    splitwise = len(files) > 1

    records: List[Tuple[str, Tuple[object, ...], int]] = []
    if splitwise:
        print(
            f"Processing {len(files)} split file(s) independently and aggregating results...",
            file=sys.stderr,
        )
    else:
        records = build_source_records(files[0], args.source_key, args.route_key, args.max_records)
        print(f"Loaded {len(records):,} source records", file=sys.stderr)

    if not splitwise and not records:
        raise SystemExit("No INT packets parsed from input log")

    if args.sweep:
        split_outputs: List[Tuple[Path, List[CacheResult]]] = []
        capacity_curves = {} if args.capacity_csv else None
        if splitwise:
            results, split_outputs = sweep_splitwise(
                files,
                args.source_key,
                args.route_key,
                args.max_records,
                use_fast=args.fast,
                capacity_curves=capacity_curves,
                capacity_sample_every=args.capacity_sample_every,
            )
        else:
            results = sweep(
                records,
                use_fast=args.fast,
                capacity_curves=capacity_curves,
                capacity_sample_every=args.capacity_sample_every,
            )
        if not args.quiet_table:
            print_results(results)
        if args.csv:
            write_csv(results, args.csv)
            if splitwise and args.csv_per_split:
                try:
                    from fyp.dash_scripts.cache_sim_source_seen import write_per_split_csvs
                except ModuleNotFoundError:
                    from cache_sim_source_seen import write_per_split_csvs  # type: ignore

                write_per_split_csvs(split_outputs, args.csv, args.csv_splits_dir)
        elif args.csv_per_split:
            print("Ignoring --csv-per-split because --csv was not provided.", file=sys.stderr)
        if args.capacity_csv and capacity_curves is not None:
            write_capacity_csv(capacity_curves, args.capacity_csv)
        return

    ttl_ps = int(args.ttl_ms * 1_000_000_000)
    fresh_ttl_ps = int(args.fresh_ttl_ms * 1_000_000_000)
    dual_dyn_ttl_ps = int(args.dual_dyn_ttl_ms * 1_000_000_000)
    pit_download_ps = int(args.pit_download_us * 1_000_000)

    cache_map = {
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
        "infinite_lp": lambda: InfiniteLastPath(),
    }

    unbounded = args.cache == "infinite_lp"
    if splitwise:
        result = run_single_splitwise(
            files,
            cache_map[args.cache],
            unbounded,
            args.source_key,
            args.route_key,
            args.max_records,
            use_fast=args.fast,
        )
    else:
        result = run_single(records, args)
    print(result)


if __name__ == "__main__":
    main()
