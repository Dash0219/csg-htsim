"""
INT route-change detector — three cache/filter strategies compared side-by-side.

Strategy A  (path-change)  : current cache = last seen path. Fire on any change.
                              Matches original behavior; 94% rate with ECMP spray.

Strategy B  (path-set)     : cache = SET of all paths ever seen for this flow.
                              Only fire when a genuinely NEW path is observed.
                              Rate drops to ~few entries per flow at startup.

Strategy C  (congestion)   : ignore path identity entirely.
                              Only fire when max(qs across hops) >= threshold.
                              Targets actual congestion events, not neutral reroutes.

Strategy D  (combined)     : fire only when BOTH a new path AND congestion together.

Usage:
  python detect_route_changes.py log2.txt
  python detect_route_changes.py log2.txt --events --limit 20
  python detect_route_changes.py log2.txt --qs-threshold 5000
"""

import re
import sys
import argparse
from collections import defaultdict

# ---------- parsing ----------------------------------------------------------

def parse(path):
    """
    Yields dicts:
      { flow, seq, hops: int,
        path: tuple(sw_id, ...),      # ordered ingress→egress
        hop_qs: tuple(qs, ...),        # queue depth at each hop
        hop_ts: tuple(ts, ...),
        hop_type: tuple(type, ...) }
    """
    header_re = re.compile(r'INT flow=(\d+) seq=(\d+) hops=(\d+)')
    hop_re    = re.compile(r'\[(\d+)\] sw=(\d+) type=(\d+) qs=(\d+) ts=(\d+)'
                           r' txbytes=(\d+) pktid=(\d+)')
    current = None
    with open(path) as f:
        for line in f:
            hm = header_re.search(line)
            if hm:
                if current is not None:
                    yield current
                current = dict(
                    flow=int(hm.group(1)),
                    seq=int(hm.group(2)),
                    hops=int(hm.group(3)),
                    sw=[], qs=[], ts=[], typ=[]
                )
                continue
            if current is None:
                continue
            hm = hop_re.search(line)
            if hm:
                current['sw'].append(int(hm.group(2)))
                current['typ'].append(int(hm.group(3)))
                current['qs'].append(int(hm.group(4)))
                current['ts'].append(int(hm.group(5)))
    if current is not None:
        yield current

# ---------- cache + detection ------------------------------------------------

def detect(records, qs_threshold=0):
    """
    Runs all four strategies over the same record stream.
    Returns a dict of results keyed by strategy name.
    """
    # Per-strategy forward counters
    results = {s: dict(fires=0, per_flow=defaultdict(int))
               for s in ('A_path_change', 'B_path_set',
                         'C_congestion', 'D_combined')}

    # Per-strategy caches
    cache_last  = {}   # A: flow -> last path tuple
    cache_set   = {}   # B: flow -> set of seen path tuples

    events_A = []
    changed_hop_counts = defaultdict(int)
    changed_hop_tier   = defaultdict(int)

    total_packets = 0
    total_flows_seen = set()

    for r in records:
        total_packets += 1
        flow  = r['flow']
        path  = tuple(r['sw'])
        max_qs = max(r['qs']) if r['qs'] else 0
        ts_last = r['ts'][-1] if r['ts'] else 0
        total_flows_seen.add(flow)

        congested = (max_qs >= qs_threshold) if qs_threshold > 0 else False

        # ---- Strategy A: last-path cache ----
        path_changed = False
        old_path = cache_last.get(flow)
        if old_path is None:
            cache_last[flow] = path
        elif path != old_path:
            path_changed = True
            results['A_path_change']['fires'] += 1
            results['A_path_change']['per_flow'][flow] += 1

            first_diff = next(
                (i for i, (a, b) in enumerate(zip(old_path, path)) if a != b),
                min(len(old_path), len(path))
            )
            changed_hop_counts[first_diff] += 1
            if first_diff < len(r['typ']):
                changed_hop_tier[r['typ'][first_diff]] += 1

            events_A.append(dict(
                flow=flow, seq=r['seq'], ts=ts_last,
                old_path=old_path, new_path=path,
                first_diff_hop=first_diff, hop_qs=tuple(r['qs']),
            ))
            cache_last[flow] = path

        # ---- Strategy B: path-set cache ----
        if flow not in cache_set:
            cache_set[flow] = {path}
        elif path not in cache_set[flow]:
            results['B_path_set']['fires'] += 1
            results['B_path_set']['per_flow'][flow] += 1
            cache_set[flow].add(path)

        # ---- Strategy C: congestion threshold ----
        if qs_threshold > 0 and congested:
            results['C_congestion']['fires'] += 1
            results['C_congestion']['per_flow'][flow] += 1

        # ---- Strategy D: new path AND congested ----
        if qs_threshold > 0 and path_changed and congested:
            results['D_combined']['fires'] += 1
            results['D_combined']['per_flow'][flow] += 1

    return dict(
        total_packets=total_packets,
        total_flows=len(total_flows_seen),
        results=results,
        events_A=events_A,
        changed_hop_counts=changed_hop_counts,
        changed_hop_tier=changed_hop_tier,
        qs_threshold=qs_threshold,
        path_set_sizes={f: len(s) for f, s in cache_set.items()},
    )


# ---------- output -----------------------------------------------------------

TIER_NAMES = {1: "ToR/Agg", 2: "Agg/Core", 3: "Core"}

def print_summary(d):
    N = d['total_packets']
    print(f"Packets parsed : {N:,}")
    print(f"Unique flows   : {d['total_flows']:,}")
    print()

    labels = {
        'A_path_change': 'A  last-path cache     (fire on any path change)',
        'B_path_set'   : 'B  path-set cache      (fire on novel path only)',
        'C_congestion' : f"C  congestion filter   (fire if max_qs >= {d['qs_threshold']})",
        'D_combined'   : f"D  combined A+C        (new path AND congested)",
    }
    print(f"{'Strategy':<52} {'Fires':>8}  {'Rate':>7}  {'Flows affected':>15}")
    print('-' * 88)
    for key, label in labels.items():
        r = d['results'][key]
        fires = r['fires']
        rate  = 100.0 * fires / N if N else 0
        fa    = len(r['per_flow'])
        if key in ('C_congestion', 'D_combined') and d['qs_threshold'] == 0:
            print(f"  {label:<50} {'(use --qs-threshold)':>8}")
        else:
            print(f"  {label:<50} {fires:>8,}  {rate:>6.2f}%  {fa:>8} / {d['total_flows']}")

    print()
    ps = d['path_set_sizes']
    if ps:
        vals = sorted(ps.values(), reverse=True)
        print(f"Unique paths per flow  (B cache state):")
        print(f"  max={vals[0]}  median={vals[len(vals)//2]}  "
              f"mean={sum(vals)/len(vals):.1f}  "
              f"total distinct paths={sum(vals)}")

    print()
    print("First-differing hop (Strategy A):")
    for idx, cnt in sorted(d['changed_hop_counts'].items()):
        print(f"  hop[{idx}]: {cnt:,}")
    print("Switch tier where path diverged:")
    for t, cnt in sorted(d['changed_hop_tier'].items()):
        print(f"  {TIER_NAMES.get(t, f'type={t}')}: {cnt:,}")


def print_events(events, limit=None):
    for e in (events[:limit] if limit else events):
        print(f"flow={e['flow']} seq={e['seq']} ts={e['ts']} "
              f"first_diff_hop={e['first_diff_hop']}")
        print(f"  old: {' -> '.join(str(s) for s in e['old_path'])}")
        print(f"  new: {' -> '.join(str(s) for s in e['new_path'])}")
        qs_str = ' '.join(f"[{i}]={q}" for i, q in enumerate(e['hop_qs']))
        print(f"  qs:  {qs_str}")


# ---------- main -------------------------------------------------------------

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('logfile', nargs='?', default='log2.txt')
    ap.add_argument('--events', action='store_true',
                    help='Print Strategy A change events')
    ap.add_argument('--limit', type=int, default=50,
                    help='Max events to print (0=all)')
    ap.add_argument('--qs-threshold', type=int, default=1000,
                    help='Queue depth threshold for strategies C and D (bytes)')
    args = ap.parse_args()

    print(f"Parsing {args.logfile} ...", file=sys.stderr)
    records = list(parse(args.logfile))
    print(f"Loaded {len(records):,} INT records", file=sys.stderr)

    d = detect(records, qs_threshold=args.qs_threshold)
    print_summary(d)

    if args.events:
        print(f"\n--- Strategy A change events (limit={args.limit or 'all'}) ---")
        print_events(d['events_A'], args.limit or None)
