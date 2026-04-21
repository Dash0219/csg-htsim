#!/usr/bin/env python3
"""
Debug cache simulator for the first N INT packets.
For each packet, this script:
1) replays it through a selected cache policy,
2) prints whether the packet was added, not added, or added but modified,
3) prints the current cache contents.

Default behavior reads only the first 100 parsed packets and writes output to
`debug_cache_sim.log`.
"""

import argparse
from pathlib import Path
from collections import OrderedDict
import re

from cache_sim import (
    InfiniteLastPath,
    LRULastPath,
    LFULastPath,
    AdmissionFilterLRU,
    PendingAdmissionLRU,
    PITCollapsedLRU,
    AdaptiveAdmissionLRU,
    OnlineAdaptiveAdmissionLRU,
    TinyCacheLRU,
    TinyLFULRU,
    TimingBloomLRU,
    FIFOLastPath,
    LRULastPathTTL,
    FreshnessInvalidationLRU,
    CacheINTFreshnessLRU,
)


def parse_packets(path: Path, max_packets: int):
    """Parse INT packets using token scanning, robust to one-line or multi-line traces."""
    text = path.read_text(errors="replace")
    token_re = re.compile(
        r"INT flow=(?P<flow>\d+) seq=(?P<seq>\d+) hops=(?P<hops>\d+)"
        r"|\[(?P<idx>\d+)\] sw=(?P<sw>\d+) type=(?P<typ>\d+) qs=(?P<qs>\d+) ts=(?P<ts>\d+) txbytes=(?P<txbytes>\d+) pktid=(?P<pktid>\d+)"
    )

    current = None
    yielded = 0

    for m in token_re.finditer(text):
        if m.group("flow") is not None:
            if current is not None:
                yield current
                yielded += 1
                if max_packets and yielded >= max_packets:
                    return
            current = {
                "flow": int(m.group("flow")),
                "seq": int(m.group("seq")),
                "hops": int(m.group("hops")),
                "sw": [],
                "qs": [],
                "ts": [],
                "typ": [],
            }
            continue

        if current is None:
            continue
        current["sw"].append(int(m.group("sw")))
        current["typ"].append(int(m.group("typ")))
        current["qs"].append(int(m.group("qs")))
        current["ts"].append(int(m.group("ts")))

    if current is not None and (not max_packets or yielded < max_packets):
        yield current


def _path_from_entry(val):
    if isinstance(val, tuple):
        first = val[0]
        if isinstance(first, tuple):
            return first
    return val if isinstance(val, tuple) else None


def get_main_store_view(cache):
    """Return a flow->path mapping for the policy's main cache store."""
    if hasattr(cache, "_store") and isinstance(cache._store, (dict, OrderedDict)):
        view = {}
        for flow, val in cache._store.items():
            if isinstance(val, set):
                # Infinite stores all seen paths per flow.
                view[flow] = f"seen_paths={len(val)}"
            else:
                path = _path_from_entry(val)
                view[flow] = path if path is not None else str(val)
        return view

    if hasattr(cache, "_probation") and hasattr(cache, "_protected"):
        view = {}
        for flow, path in cache._probation.items():
            view[flow] = f"probation:{path}"
        for flow, path in cache._protected.items():
            view[flow] = f"protected:{path}"
        return view

    return {}


def format_cache_dump(cache):
    lines = [f"  policy={cache.name} capacity={cache.capacity}"]

    if hasattr(cache, "_store") and isinstance(cache._store, (dict, OrderedDict)):
        if not cache._store:
            lines.append("  main_cache=<empty>")
        else:
            lines.append("  main_cache:")
            for flow, val in cache._store.items():
                lines.append(f"    flow={flow} value={val}")

    if hasattr(cache, "_probation") and hasattr(cache, "_protected"):
        lines.append("  probation:")
        if cache._probation:
            for flow, path in cache._probation.items():
                lines.append(f"    flow={flow} path={path}")
        else:
            lines.append("    <empty>")
        lines.append("  protected:")
        if cache._protected:
            for flow, path in cache._protected.items():
                lines.append(f"    flow={flow} path={path}")
        else:
            lines.append("    <empty>")

    if hasattr(cache, "_pending") and isinstance(cache._pending, (dict, OrderedDict)):
        lines.append("  pending:")
        if cache._pending:
            for flow, path in cache._pending.items():
                lines.append(f"    flow={flow} path={path}")
        else:
            lines.append("    <empty>")

    return "\n".join(lines)


def make_cache(args):
    ttl_ps = int(args.ttl_ms * 1_000_000_000)
    fresh_ttl_ps = int(args.fresh_ttl_ms * 1_000_000_000)
    dual_dyn_ttl_ps = int(args.dual_dyn_ttl_ms * 1_000_000_000)
    pit_download_ps = int(args.pit_download_us * 1_000_000)

    cache_map = {
        "lru": lambda: LRULastPath(args.size),
        "lfu": lambda: LFULastPath(args.size),
        "admission": lambda: AdmissionFilterLRU(args.size, pending_reset_every=args.pending_reset_every),
        "pending_admission": lambda: PendingAdmissionLRU(args.size, pending_reset_every=args.pending_reset_every),
        "pit": lambda: PITCollapsedLRU(args.size, download_delay_ps=pit_download_ps),
        "adaptive": lambda: AdaptiveAdmissionLRU(args.size, pending_reset_every=args.pending_reset_every),
        "online_adaptive": lambda: OnlineAdaptiveAdmissionLRU(args.size),
        "bloom": lambda: TimingBloomLRU(args.size, args.bloom_bits, args.bloom_hashes, args.bloom_epoch_records),
        "fifo": lambda: FIFOLastPath(args.size),
        "tiny_cache": lambda: TinyCacheLRU(args.size),
        "tiny_lfu": lambda: TinyLFULRU(args.size),
        "lru_ttl": lambda: LRULastPathTTL(args.size, ttl_ps),
        "f_inv": lambda: FreshnessInvalidationLRU(args.size, fresh_ttl_ps),
        "cache_int": lambda: CacheINTFreshnessLRU(args.size, dual_dyn_ttl_ps, args.dual_stable_hits),
        "infinite_lp": lambda: InfiniteLastPath(),
    }
    return cache_map[args.cache]()


def classify_action(before, after, flow, path):
    had_flow = flow in before
    has_flow_after = flow in after
    old = before.get(flow)

    if had_flow:
        return "not added" if old == path else "added but modified"
    if has_flow_after:
        return "added"
    return "not added"


def parse_args():
    ap = argparse.ArgumentParser(description="Debug cache simulation for first N packets")
    ap.add_argument("logfile", nargs="?", default="dash_dataset/synthetic/log_incast.txt")
    ap.add_argument("--max-packets", type=int, default=100, help="Number of parsed packets to process")
    ap.add_argument(
        "--cache",
        choices=[
            "lru",
            "lfu",
            "admission",
            "pending_admission",
            "pit",
            "adaptive",
            "online_adaptive",
            "bloom",
            "fifo",
            "tiny_cache",
            "tiny_lfu",
            "lru_ttl",
            "f_inv",
            "cache_int",
            "infinite_lp",
        ],
        default="lru",
        help="Cache policy",
    )
    ap.add_argument("--size", type=int, default=4, help="Cache capacity (flow slots)")
    ap.add_argument("--pending-reset-every", type=int, default=0)
    ap.add_argument("--bloom-bits", type=int, default=1 << 18)
    ap.add_argument("--bloom-hashes", type=int, default=4)
    ap.add_argument("--bloom-epoch-records", type=int, default=256)
    ap.add_argument("--ttl-ms", type=float, default=10.0)
    ap.add_argument("--fresh-ttl-ms", type=float, default=2.0)
    ap.add_argument("--dual-dyn-ttl-ms", type=float, default=0.5)
    ap.add_argument("--dual-stable-hits", type=int, default=3)
    ap.add_argument("--pit-download-us", type=float, default=2.0)
    ap.add_argument("--out", default="debug_cache_sim.log", help="Output debug log file")
    return ap.parse_args()


def main():
    args = parse_args()
    log_path = Path(args.logfile)
    out_path = Path(args.out)

    cache = make_cache(args)
    packets = list(parse_packets(log_path, args.max_packets))

    lines = []
    lines.append(f"input={log_path}")
    lines.append(f"cache={args.cache} size={args.size}")
    lines.append(f"processed_packets={len(packets)}")
    lines.append("=" * 80)

    for idx, pkt in enumerate(packets, start=1):
        flow = pkt["flow"]
        path = tuple(pkt["sw"])
        ts = pkt["ts"][-1] if pkt["ts"] else 0

        before = get_main_store_view(cache)
        hit, evicted = cache.lookup_and_update(flow, path, ts)
        after = get_main_store_view(cache)
        action = classify_action(before, after, flow, path)

        lines.append(
            f"pkt={idx} flow={flow} seq={pkt['seq']} hops={pkt['hops']} "
            f"hit={hit} evicted={evicted} action={action}"
        )
        lines.append(f"  path={path}")
        lines.append(format_cache_dump(cache))
        lines.append("-" * 80)

    out_path.write_text("\n".join(lines) + "\n")
    print(f"Wrote debug log to {out_path}")


if __name__ == "__main__":
    main()
