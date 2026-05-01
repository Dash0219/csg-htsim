"""
Source-only cache simulator for IMC packet tables.

This variant keeps the same cache policy designs as cache_sim.py, but uses a
source-keyed route signatures derived from packet table columns.

Why this exists:
  IMC packet traces at one capture point do not contain full per-hop path
    telemetry, so path-change suppression is approximated from route signatures
    (for example per-source destination changes).

Input format:
  Text table from convert_imc_pcap_to_txt.py (tab-separated by default).

Output format:
  Same table and CSV schema as cache_sim.py for easy comparison/plotting.
"""

from __future__ import annotations

import argparse
import csv
import sys
import re
from glob import glob
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Sequence, Tuple, Union, cast

try:
    from fyp.scripts.cache_sim import (
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
        cache_slots_used,
        print_results,
        write_csv,
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
        cache_slots_used,
        print_results,
        write_csv,
    )

try:
    from cache_sim_fast import simulate_source_seen_records as _simulate_source_seen_records_fast  # pyright: ignore[reportMissingImports]
except Exception:
    _simulate_source_seen_records_fast = None


SWEEP_SIZES = [4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096]

# Compact source-seen record format used by large split replays:
# (source, route_signature, timestamp_ps)
SourceRecord = Union[Dict[str, object], Tuple[str, tuple, int]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_path", help="Input IMC txt file or directory.")
    parser.add_argument(
        "--pattern",
        default="*_pt*.txt",
        help="Glob when input_path is a directory (default: %(default)s).",
    )
    parser.add_argument(
        "--source-column",
        default="src_ip",
        help="Source node column used for seen-before checks (default: %(default)s).",
    )
    parser.add_argument(
        "--route-columns",
        default="dst_ip,dst_port,l4_proto",
        help=(
            "Comma-separated columns used as route signature per source "
            "(default: %(default)s)."
        ),
    )
    parser.add_argument(
        "--timestamp-column",
        default="timestamp",
        help="Timestamp column in seconds (default: %(default)s).",
    )
    parser.add_argument(
        "--max-records",
        type=int,
        default=0,
        help="Maximum packet records to load (0 means all).",
    )
    parser.add_argument("--sweep", action="store_true", help="Sweep all policies and sizes.")
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Use the optional fast source-seen simulation path if available",
    )
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
    parser.add_argument(
        "--bloom-bits",
        type=int,
        default=1 << 18,
        help="Bloom filter size in bits per filter (default: 262144)",
    )
    parser.add_argument(
        "--bloom-hashes",
        type=int,
        default=4,
        help="Number of Bloom hash functions (default: 4)",
    )
    parser.add_argument(
        "--bloom-epoch-records",
        type=int,
        default=256,
        help="Rotate Bloom windows every N records",
    )
    parser.add_argument(
        "--ttl-ms",
        type=float,
        default=10.0,
        help="Keep-alive TTL in milliseconds for LRUTTL",
    )
    parser.add_argument(
        "--fresh-ttl-ms",
        type=float,
        default=2.0,
        help="Freshness TTL in milliseconds for FreshnessInvalidationLRU",
    )
    parser.add_argument(
        "--dual-dyn-ttl-ms",
        type=float,
        default=0.5,
        help="Dynamic-class TTL in milliseconds for DualFreshnessLRU",
    )
    parser.add_argument(
        "--dual-stable-hits",
        type=int,
        default=3,
        help="Stable hits needed to promote a flow to static class in CacheINTFreshnessLRU",
    )
    parser.add_argument(
        "--pit-download-us",
        type=float,
        default=2.0,
        help="PIT download delay in microseconds for PITCollapsedLRU",
    )
    parser.add_argument(
        "--life-min-ttl-ms",
        type=float,
        default=0.1,
        help="Minimum per-flow TTL in milliseconds for FlowLifetimeAdaptiveTTL",
    )
    parser.add_argument(
        "--life-max-ttl-ms",
        type=float,
        default=20.0,
        help="Maximum per-flow TTL in milliseconds for FlowLifetimeAdaptiveTTL",
    )
    parser.add_argument(
        "--life-ema-alpha",
        type=float,
        default=0.2,
        help="EMA alpha for per-flow gap learning in FlowLifetimeAdaptiveTTL",
    )
    parser.add_argument(
        "--life-ttl-multiplier",
        type=float,
        default=4.0,
        help="Multiplier mapping learned inter-arrival gap to TTL in FlowLifetimeAdaptiveTTL",
    )
    parser.add_argument("--csv", metavar="FILE", help="Write results to CSV")
    parser.add_argument(
        "--csv-per-split",
        action="store_true",
        help=(
            "When input_path is a directory, also write one CSV per matched split file "
            "(requires --csv)."
        ),
    )
    parser.add_argument(
        "--csv-splits-dir",
        default="",
        help=(
            "Directory for per-split CSV outputs. Default: sibling folder named "
            "<total_csv_stem>_splits next to --csv"
        ),
    )
    return parser.parse_args()


def sniff_delimiter(path: Path) -> str:
    with path.open("r", encoding="utf-8", newline="") as f:
        header = f.readline()
    if "\t" in header:
        return "\t"
    if "," in header:
        return ","
    return "\t"


def resolve_inputs(input_path: Path, pattern: str) -> List[Path]:
    if input_path.is_file():
        return [input_path]
    if not input_path.is_dir():
        raise FileNotFoundError(f"Input path does not exist: {input_path}")
    files = [Path(p) for p in glob(str(input_path / pattern)) if Path(p).is_file()]
    files.sort(key=lambda p: p.name)
    if not files:
        raise FileNotFoundError(f"No matching files under {input_path} with pattern {pattern}")
    return files


def to_picoseconds(ts_text: str) -> int:
    if not ts_text:
        return 0
    try:
        return int(round(float(ts_text) * 1_000_000_000_000))
    except ValueError:
        return 0


def load_records(
    files: Sequence[Path],
    source_column: str,
    route_columns: Sequence[str],
    timestamp_column: str,
    max_records: int,
) -> List[Dict[str, object]]:
    records: List[Dict[str, object]] = []

    for path in files:
        delimiter = sniff_delimiter(path)
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            for row in reader:
                src = (row.get(source_column) or "").strip()
                if not src:
                    continue
                ts_ps = to_picoseconds((row.get(timestamp_column) or "").strip())
                route_sig = tuple((row.get(col) or "").strip() for col in route_columns)
                records.append({"source": src, "route_sig": route_sig, "ts_ps": ts_ps})
                if max_records > 0 and len(records) >= max_records:
                    return records

    return records


def _unpack_source_record(rec: SourceRecord) -> Tuple[str, tuple, int]:
    if isinstance(rec, tuple):
        return rec
    source = cast(str, rec["source"])
    route_sig = cast(tuple, rec["route_sig"])
    ts_ps = cast(int, rec["ts_ps"])
    return source, route_sig, ts_ps


def simulate_source(
    records: Iterable[SourceRecord],
    cache,
    oracle=None,
    use_fast=False,
    capacity_samples=None,
    capacity_sample_every=1000,
) -> CacheResult:
    result = CacheResult(cache_name=cache.name, capacity=cache.capacity)
    track_capacity = capacity_samples is not None and cache.capacity != float('inf')

    if track_capacity:
        use_fast = False

    # Fast path currently expects dict-backed records with source/route_sig/ts_ps keys.
    fast_eligible = (
        use_fast
        and _simulate_source_seen_records_fast is not None
        and isinstance(records, list)
        and (not records or isinstance(records[0], dict))
    )

    if fast_eligible:
        (
            total,
            hits,
            necessary_forwards,
            new_route_forwards,
            route_change_forwards,
            redundant_forwards,
            evictions,
        ) = _simulate_source_seen_records_fast(records, cache)
        result.total = total
        result.hits = hits
        result.necessary_forwards = necessary_forwards
        result.new_route_forwards = new_route_forwards
        result.route_change_forwards = route_change_forwards
        result.redundant_forwards = redundant_forwards
        result.evictions = evictions
        return result

    collector_seen_paths = {}

    sample_every = max(1, int(capacity_sample_every))
    last_ts = 0

    for rec in records:
        source, route_sig, ts_ps = _unpack_source_record(rec)
        last_ts = ts_ps
        key = source
        path_token = route_sig

        result.total += 1
        hit, evicted = cache.lookup_and_update(key, path_token, ts_ps)
        if evicted:
            result.evictions += 1

        if hit:
            result.hits += 1
            continue

        seen_paths = collector_seen_paths.get(key)
        if seen_paths is None:
            result.necessary_forwards += 1
            result.new_route_forwards += 1
            collector_seen_paths[key] = {path_token}
        elif path_token not in seen_paths:
            result.necessary_forwards += 1
            result.route_change_forwards += 1
            seen_paths.add(path_token)
        else:
            result.redundant_forwards += 1

        if track_capacity and (result.total == 1 or result.total % sample_every == 0):
            slots = cache_slots_used(cache)
            if slots is not None:
                capacity_samples.append((result.total, ts_ps, slots))

    if track_capacity and result.total > 0:
        slots = cache_slots_used(cache)
        if slots is not None and (
            not capacity_samples or capacity_samples[-1][0] != result.total
        ):
            capacity_samples.append((result.total, last_ts, slots))

    return result


def run_oracle_and_cache(
    records: Sequence[SourceRecord],
    cache_factory,
    use_fast=False,
    capacity_curves=None,
    capacity_sample_every=1000,
):
    oracle = InfiniteLastPath()
    cache = cache_factory()
    samples = [] if capacity_curves is not None else None
    result = simulate_source(
        records,
        cache,
        oracle,
        use_fast=use_fast,
        capacity_samples=samples,
        capacity_sample_every=capacity_sample_every,
    )
    if capacity_curves is not None and samples:
        capacity_curves[(result.cache_name, int(result.capacity))] = samples
    return result


def sanitize_name(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
    cleaned = cleaned.strip("._-")
    return cleaned or "split"


def split_csv_dir(total_csv: str, override_dir: str) -> Path:
    total_path = Path(total_csv)
    if override_dir:
        out = Path(override_dir)
    else:
        out = total_path.parent / f"{total_path.stem}_splits"
    out.mkdir(parents=True, exist_ok=True)
    return out


def write_per_split_csvs(
    split_results: Sequence[Tuple[Path, List[CacheResult]]],
    total_csv: str,
    override_dir: str,
) -> None:
    out_dir = split_csv_dir(total_csv, override_dir)
    for idx, (path, results) in enumerate(split_results, start=1):
        stem = sanitize_name(path.stem)
        out_path = out_dir / f"split_{idx:02d}_{stem}.csv"
        write_csv(results, str(out_path))
    print(f"Per-split CSV files written to {out_dir}", file=sys.stderr)


def merge_results(dest: CacheResult, src: CacheResult) -> None:
    """Add counters from src into dest for split-wise aggregation."""
    dest.total += src.total
    dest.hits += src.hits
    dest.necessary_forwards += src.necessary_forwards
    dest.new_route_forwards += src.new_route_forwards
    dest.route_change_forwards += src.route_change_forwards
    dest.redundant_forwards += src.redundant_forwards
    dest.evictions += src.evictions


def load_split_records(path: Path, args: argparse.Namespace) -> List[Dict[str, object]]:
    return load_records(
        files=[path],
        source_column=args.source_column,
        route_columns=[c.strip() for c in args.route_columns.split(",") if c.strip()],
        timestamp_column=args.timestamp_column,
        max_records=args.max_records,
    )


def sweep_splitwise(
    files: Sequence[Path], args: argparse.Namespace, use_fast=False
) -> Tuple[List[CacheResult], List[Tuple[Path, List[CacheResult]]]]:
    by_key: Dict[Tuple[str, object], CacheResult] = {}
    order: List[Tuple[str, object]] = []
    split_outputs: List[Tuple[Path, List[CacheResult]]] = []

    for idx, path in enumerate(files, start=1):
        print(f"Loading split {idx}/{len(files)}: {path.name}", file=sys.stderr)
        records = load_split_records(path, args)
        print(f"  Loaded {len(records):,} source records", file=sys.stderr)
        split_results = sweep(records, use_fast=args.fast)
        split_outputs.append((path, split_results))
        for r in split_results:
            key = (r.cache_name, r.capacity)
            if key not in by_key:
                by_key[key] = CacheResult(cache_name=r.cache_name, capacity=r.capacity)
                order.append(key)
            merge_results(by_key[key], r)

    return [by_key[k] for k in order], split_outputs


def run_single_splitwise(files: Sequence[Path], cache_factory, unbounded: bool, args: argparse.Namespace, use_fast=False) -> CacheResult:
    seed_cache = cache_factory()
    total_result = CacheResult(cache_name=seed_cache.name, capacity=seed_cache.capacity)

    for idx, path in enumerate(files, start=1):
        print(f"Loading split {idx}/{len(files)}: {path.name}", file=sys.stderr)
        records = load_split_records(path, args)
        print(f"  Loaded {len(records):,} source records", file=sys.stderr)

        split_cache = cache_factory()
        split_oracle = None if unbounded else InfiniteLastPath()
        split_result = simulate_source(records, split_cache, split_oracle, use_fast=args.fast)
        merge_results(total_result, split_result)

    return total_result


def sweep(
    records: Sequence[SourceRecord],
    use_fast=False,
    capacity_curves=None,
    capacity_sample_every=1000,
) -> List[CacheResult]:
    results: List[CacheResult] = []
    results.append(simulate_source(records, InfiniteLastPath(), oracle=None, use_fast=use_fast))

    ttl_sweep = {
        "0.1ms": 100_000_000,
        "0.5ms": 500_000_000,
        "2ms": 2_000_000_000,
        "10ms": 10_000_000_000,
    }

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
            results.append(
                run_oracle_and_cache(
                    records,
                    factory,
                    use_fast=use_fast,
                    capacity_curves=capacity_curves,
                    capacity_sample_every=capacity_sample_every,
                )
            )

        for label, ttl_ps in ttl_sweep.items():
            r = run_oracle_and_cache(
                records,
                lambda s=size, t=ttl_ps: LRULastPathTTL(s, t),
                use_fast=use_fast,
                capacity_curves=capacity_curves,
                capacity_sample_every=capacity_sample_every,
            )
            r.cache_name = f"LRUTtl({label})"
            if capacity_curves is not None:
                old_key = ("LRUTTL", int(r.capacity))
                if old_key in capacity_curves:
                    capacity_curves[(r.cache_name, int(r.capacity))] = capacity_curves.pop(old_key)
            results.append(r)

    return results


def main() -> None:  # pragma: no cover
    args = parse_args()
    input_path = Path(args.input_path)
    files = resolve_inputs(input_path, args.pattern)
    records: List[Dict[str, object]] = []

    splitwise = len(files) > 1
    if splitwise:
        print(
            f"Processing {len(files)} split file(s) independently and aggregating results...",
            file=sys.stderr,
        )
    else:
        print(f"Loading IMC table records from {len(files)} file(s)...", file=sys.stderr)
        records = load_split_records(files[0], args)
        print(f"Loaded {len(records):,} source records", file=sys.stderr)

    if args.sweep:
        split_outputs: List[Tuple[Path, List[CacheResult]]] = []
        if splitwise:
            results, split_outputs = sweep_splitwise(files, args)
        else:
            results = sweep(records)
        print_results(results)
        if args.csv:
            write_csv(results, args.csv)
            if splitwise and args.csv_per_split:
                write_per_split_csvs(split_outputs, args.csv, args.csv_splits_dir)
        elif args.csv_per_split:
            print("Ignoring --csv-per-split because --csv was not provided.", file=sys.stderr)
        return

    ttl_ps = int(args.ttl_ms * 1_000_000_000)
    fresh_ttl_ps = int(args.fresh_ttl_ms * 1_000_000_000)
    dual_dyn_ttl_ps = int(args.dual_dyn_ttl_ms * 1_000_000_000)
    pit_download_ps = int(args.pit_download_us * 1_000_000)
    life_min_ttl_ps = int(args.life_min_ttl_ms * 1_000_000_000)
    life_max_ttl_ps = int(args.life_max_ttl_ms * 1_000_000_000)
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
        "life_ttl": lambda: FlowLifetimeAdaptiveTTL(
            args.size,
            min_ttl_ps=life_min_ttl_ps,
            max_ttl_ps=life_max_ttl_ps,
            ema_alpha=args.life_ema_alpha,
            ttl_multiplier=args.life_ttl_multiplier,
        ),
        "infinite_lp": lambda: InfiniteLastPath(),
    }

    unbounded = args.cache == "infinite_lp"
    cache_factory = cache_map[args.cache]
    if splitwise:
        result = run_single_splitwise(files, cache_factory, unbounded, args)
    else:
        cache = cache_factory()
        oracle = None if unbounded else InfiniteLastPath()
        result = simulate_source(records, cache, oracle)
    print(result)


if __name__ == "__main__":
    main()
