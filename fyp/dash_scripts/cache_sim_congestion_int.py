"""
Congestion-event cache simulator for synthetic INT logs.

This is the third evaluation track alongside route-change and source-seen modes.
It extracts congestion events from INT hop queue sizes and reuses the same cache
policies/output schema as cache_sim.py.

Default behavior:
  - key-level: switch (switch_id, switch_type)
  - signature: seen (all anomalies for a key share one signature)
  - event condition: hop queue size >= --qs-threshold

Range mode (--range-threshold > 0):
  - Implements INTCollector-style adaptive-baseline event detection.
  - cache value = actual queue size; event fires when |new_qs - cached_qs| > range_threshold.
  - After each event the cached baseline updates to the new queue size.
  - Records within the tolerance band are suppressed without changing the baseline.
  - Only supported for --key-level switch.

Rationale:
  Congestion is fundamentally a per-resource (queue/link) condition, so the
  default key is per switch/type, not per flow. A flow-key mode is provided for
  comparison and attribution experiments.
"""

from __future__ import annotations

import argparse
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Sequence, Tuple, cast

try:
    from fyp.dash_scripts.cache_sim import (
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
        write_capacity_csv,
    )
    from fyp.dash_scripts.cache_sim_source_seen import (
        SWEEP_SIZES,
        simulate_source,
        sweep,
        write_per_split_csvs,
    )
except ModuleNotFoundError:
    from cache_sim import (  # type: ignore
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
        write_capacity_csv,
    )
    from cache_sim_source_seen import (  # type: ignore
        SWEEP_SIZES,
        simulate_source,
        sweep,
        write_per_split_csvs,
    )


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
            "'bucket' tracks queue severity buckets. Ignored when --range-threshold > 0."
        ),
    )
    parser.add_argument(
        "--bucket-bytes",
        type=int,
        default=8192,
        help="Queue-size bucket width when --signature bucket",
    )
    parser.add_argument(
        "--range-threshold",
        type=int,
        default=8192,
        help=(
            "INTCollector-style range-based event detection: forward only when "
            "|new_qs - cached_qs| > RANGE_THRESHOLD bytes. 0 disables range mode "
            "and falls back to --signature mode (default: %(default)s). "
            "Requires --key-level switch."
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
    use_range = args.range_threshold > 0 and args.key_level == "switch"

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
                # Range mode stores the actual queue size; equality mode uses seen/bucket signature.
                route_sig: tuple = (qs[i],) if use_range else make_signature(qs[i], sw[i], typ[i], args)
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


# ---------------------------------------------------------------------------
# INTCollector-style range-based congestion simulation
# ---------------------------------------------------------------------------

def _store_of(cache) -> "Dict | None":
    """Return the cache's primary per-key storage dict, or None if inaccessible."""
    s = getattr(cache, '_store', None)
    if isinstance(s, (dict, OrderedDict)):
        return s
    return None


def simulate_congestion_range(
    records: List[Dict[str, object]],
    cache,
    oracle_baselines: Dict[str, int],
    range_threshold: int,
) -> CacheResult:
    """
    INTCollector-style range-based congestion event simulation.

    Forwards a record only when |new_qs - cached_qs| > range_threshold.
    The cached baseline updates to the new queue size on each forward.
    Records within the tolerance band are suppressed without changing the baseline.

    oracle_baselines is an unbounded dict {source -> last_forwarded_qs} shared
    across calls for the same experiment run; pass a fresh dict per independent run.
    """
    result = CacheResult(cache_name=cache.name, capacity=cache.capacity)
    # Tracks the currently-cached queue size for each switch key in the bounded cache.
    cache_baselines: Dict[str, int] = {}
    store = _store_of(cache)

    for rec in records:
        source = str(rec["source"])
        new_qs = int(cast(tuple, rec["route_sig"])[0])
        ts_ps = int(cast(int, rec["ts_ps"]))
        result.total += 1

        # Oracle: unbounded adaptive-baseline range check
        prev_oracle = oracle_baselines.get(source)
        if prev_oracle is None or abs(new_qs - prev_oracle) > range_threshold:
            oracle_necessary = True
            oracle_baselines[source] = new_qs
        else:
            oracle_necessary = False

        # Bounded cache decision
        if source in cache_baselines:
            cached_qs = cache_baselines[source]
            if abs(new_qs - cached_qs) <= range_threshold:
                # Within tolerance band: suppress.
                # Call with the stored value so LRU/LFU ordering is maintained.
                cache.lookup_and_update(source, (cached_qs,), ts_ps)
                result.hits += 1
                continue
            # Range exceeded: event → forward, update stored baseline.
            # Updating an existing slot; no eviction expected.
            cache.lookup_and_update(source, (new_qs,), ts_ps)
            cache_baselines[source] = new_qs
        else:
            # Key not tracked: miss → insert and potentially evict LRU victim.
            _, evicted = cache.lookup_and_update(source, (new_qs,), ts_ps)
            cache_baselines[source] = new_qs
            if evicted:
                result.evictions += 1
                # Remove evicted keys from cache_baselines by diffing against store.
                if store is not None:
                    dead = [k for k in cache_baselines if k != source and k not in store]
                    for k in dead:
                        del cache_baselines[k]

        # Count this record as a forward
        if oracle_necessary:
            if prev_oracle is None:
                result.new_route_forwards += 1
            else:
                result.route_change_forwards += 1
            result.necessary_forwards += 1
        else:
            result.redundant_forwards += 1

    return result


def sweep_congestion_range(
    records: List[Dict[str, object]],
    range_threshold: int,
) -> List[CacheResult]:
    """Run all standard policy/capacity combinations with range-based event detection."""
    results: List[CacheResult] = []

    # Unbounded oracle row
    oracle_baselines: Dict[str, int] = {}
    results.append(simulate_congestion_range(records, InfiniteLastPath(), oracle_baselines, range_threshold))

    for size in SWEEP_SIZES:
        for factory in [
            lambda s=size: LRULastPath(s),
            lambda s=size: FIFOLastPath(s),
            lambda s=size: LFULastPath(s),
            lambda s=size: AdmissionFilterLRU(s),
            lambda s=size: PendingAdmissionLRU(s),
            lambda s=size: PITCollapsedLRU(s),
            lambda s=size: AdaptiveAdmissionLRU(s),
            lambda s=size: OnlineAdaptiveAdmissionLRU(s),
            lambda s=size: TimingBloomLRU(s),
            lambda s=size: TinyCacheLRU(s),
            lambda s=size: TinyLFULRU(s),
            lambda s=size: FreshnessInvalidationLRU(s),
            lambda s=size: CacheINTFreshnessLRU(s),
            lambda s=size: FlowLifetimeAdaptiveTTL(s),
        ]:
            oracle_baselines = {}
            results.append(simulate_congestion_range(records, factory(), oracle_baselines, range_threshold))

    return results


# ---------------------------------------------------------------------------
# Cache factory and sweep plumbing
# ---------------------------------------------------------------------------

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


def sweep_splitwise(
    files: Sequence[Path],
    args: argparse.Namespace,
    capacity_curves=None,
) -> Tuple[List[CacheResult], List[Tuple[Path, List[CacheResult]]]]:
    by_key: Dict[Tuple[str, object], CacheResult] = {}
    order: List[Tuple[str, object]] = []
    split_outputs: List[Tuple[Path, List[CacheResult]]] = []
    record_offset = 0
    use_range = args.range_threshold > 0 and args.key_level == "switch"

    for idx, path in enumerate(files, start=1):
        print(f"Loading split {idx}/{len(files)}: {path.name}", file=sys.stderr)
        records = build_congestion_records(path, args)
        print(f"  Loaded {len(records):,} congestion records", file=sys.stderr)
        split_capacity_curves = {} if capacity_curves is not None else None

        if use_range:
            split_results = sweep_congestion_range(records, args.range_threshold)
        else:
            split_results = sweep(
                records,
                use_fast=args.fast,
                capacity_curves=split_capacity_curves,
                capacity_sample_every=args.capacity_sample_every,
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


def run_single_splitwise(files: Sequence[Path], cache_factory, unbounded: bool, args: argparse.Namespace) -> CacheResult:
    seed_cache = cache_factory()
    total_result = CacheResult(cache_name=seed_cache.name, capacity=seed_cache.capacity)
    use_range = args.range_threshold > 0 and args.key_level == "switch"

    for idx, path in enumerate(files, start=1):
        print(f"Loading split {idx}/{len(files)}: {path.name}", file=sys.stderr)
        records = build_congestion_records(path, args)
        print(f"  Loaded {len(records):,} congestion records", file=sys.stderr)

        split_cache = cache_factory()
        if use_range:
            oracle_baselines: Dict[str, int] = {}
            split_result = simulate_congestion_range(records, split_cache, oracle_baselines, args.range_threshold)
        else:
            split_oracle = None if unbounded else InfiniteLastPath()
            split_result = simulate_source(records, split_cache, split_oracle, use_fast=args.fast)
        merge_results(total_result, split_result)

    return total_result


def main() -> None:
    args = parse_args()

    if args.range_threshold > 0 and args.key_level != "switch":
        print("ERROR: --range-threshold requires --key-level switch", file=sys.stderr)
        sys.exit(1)

    input_path = Path(args.input_path)
    files = resolve_inputs(input_path, args.pattern)
    splitwise = len(files) > 1
    use_range = args.range_threshold > 0 and args.key_level == "switch"

    records: List[Dict[str, object]] = []
    if splitwise:
        print(f"Processing {len(files)} split file(s) independently and aggregating results...", file=sys.stderr)
    else:
        records = build_congestion_records(files[0], args)
        print(f"Loaded {len(records):,} congestion records", file=sys.stderr)

    if args.sweep:
        split_outputs: List[Tuple[Path, List[CacheResult]]] = []
        capacity_curves = {} if args.capacity_csv and not use_range else None
        if splitwise:
            results, split_outputs = sweep_splitwise(files, args, capacity_curves=capacity_curves)
        elif use_range:
            results = sweep_congestion_range(records, args.range_threshold)
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
                write_per_split_csvs(split_outputs, args.csv, args.csv_splits_dir)
        elif args.csv_per_split:
            print("Ignoring --csv-per-split because --csv was not provided.", file=sys.stderr)
        if args.capacity_csv and capacity_curves is not None:
            write_capacity_csv(capacity_curves, args.capacity_csv)
        return

    factories = cache_factory_map(args)
    unbounded = args.cache == "infinite_lp"
    if splitwise:
        result = run_single_splitwise(files, factories[args.cache], unbounded, args)
    elif use_range:
        oracle_baselines: Dict[str, int] = {}
        cache = factories[args.cache]()
        result = simulate_congestion_range(records, cache, oracle_baselines, args.range_threshold)
    else:
        cache = factories[args.cache]()
        oracle = None if unbounded else InfiniteLastPath()
        result = simulate_source(records, cache, oracle, use_fast=args.fast)
    print(result)


if __name__ == "__main__":
    main()
