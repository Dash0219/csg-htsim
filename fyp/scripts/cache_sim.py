"""
INT sink-side path cache simulator.

Models a bounded hardware cache at the sink node.  The cache decides whether
to forward an incoming INT record to the collector or suppress it.

A forward is *necessary* if the collector does not already have this path for
this flow (the oracle — infinite memory — would also forward it).
A forward is *redundant* if the collector already holds the current path, but
the bounded cache evicted the flow entry and lost track of it.

Implemented caches
------------------
    Infinite              — unbounded dict: flow → last_path       (oracle / baseline)
    LRU(N)                — N slots, LRU eviction, stores last path per flow
    FIFO(N)               — N slots, FIFO eviction
    LFU(N)                — N slots, LFU eviction (least-frequently-seen flow evicted)
                                                    classic frequency vs recency comparison against LRU
        OneHitWonderLRU(N)    — N slots, LRU eviction, but only admits a flow after its
                                                        second encounter within a recent Bloom window.
                                                        Filters short-lived flows that would otherwise pollute the cache.
        PendingAdmissionLRU(N) — N slots, LRU eviction + exact pending table.
                                                        New flows are admitted on second touch using an exact FIFO
                                                        pending sketch (legacy baseline).
        PITCollapsedLRU(N)     — N slots, PIT-style inflight collapsing before cache admission.
                                                        Collapses repeated requests while content is downloading.
        AdaptiveAdmissionLRU(N) — OneHitWonderLRU with pressure-adaptive bypass.
                                                        Under low eviction pressure, behaves like plain LRU
                                                        (admits immediately). Under high pressure, switches
                                                        to second-chance admission to reduce pollution.
        OnlineAdaptiveAdmissionLRU(N)
                                                        — AdaptiveAdmissionLRU with online mode switching.
        TimeLimitedBloomLRU(N)  — Time-limited Bloom admission with rolling freshness.
                                                        Bloom gating is only enforced while the cache is
                                                        under sustained eviction pressure.
        TinyLFULRU(N)           — N slots, LRU eviction + TinyLFU admission sketch.
                                                        Candidates are admitted only when estimated frequency
                                                        exceeds the current LRU victim's frequency.
        TinyCacheLRU(N)         — N slots, LRU eviction + TinyCache admission filter.
                                                        Uses a table of recent fingerprints, random eviction
                                                        within a set when full, and a set-local frequency estimate.
        FreshnessInvalidationLRU(N)
                                                        — N slots, LRU + hard freshness expiration.
                                                        Expired entries are invalidated before decision,
                                                        approximating collector-driven stale-state purge.
        CacheINTFreshnessLRU(N) — N slots, Cache-INT-inspired split handling:
                                                        time-variant entries use freshness TTL,
                                                        stable entries are static (no TTL), and eviction
                                                        prefers least-fresh dynamic entries.
        FlowLifetimeAdaptiveTTL(N)
                                                        — N slots, per-flow adaptive freshness window derived
                                                        from observed inter-arrival gaps.

Archived helper policies remain in the file for reference, but are not surfaced
by the default CLI policy list:
    VolatilityAwareLRU, SegmentedLRU, TwoFilterOHWLRU, DualFreshnessLRU,
    OnlineAdaptiveDualTTL

Usage
-----
  # single run
  python cache_sim.py dash_logs/log2.txt --cache lru --size 64

  # sweep cache sizes and compare policies
  python cache_sim.py dash_logs/log2.txt --sweep
  python cache_sim.py dash_logs/log2.txt --sweep --csv results.csv
"""

import re
import sys
import csv
import heapq
import argparse
import hashlib
import random
import math
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import cast

try:
    from cache_sim_fast import simulate_records as _simulate_records_fast  # pyright: ignore[reportMissingImports]
except Exception:
    _simulate_records_fast = None


# ---------------------------------------------------------------------------
# Trace parser (shared with detect_route_changes.py)
# ---------------------------------------------------------------------------

def parse(path):
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
                cast(list, current['sw']).append(int(hm.group(2)))
                cast(list, current['typ']).append(int(hm.group(3)))
                cast(list, current['qs']).append(int(hm.group(4)))
                cast(list, current['ts']).append(int(hm.group(5)))
    if current is not None:
        yield current


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class CacheResult:
    cache_name: str
    capacity: int               # float('inf') for unbounded
    total: int = 0
    hits: int = 0               # suppressed (correctly)
    necessary_forwards: int = 0 # collector-needed forwards (new route + route change)
    new_route_forwards: int = 0 # first time a flow route is observed by collector
    route_change_forwards: int = 0 # known flow but route differs from collector's last route
    redundant_forwards: int = 0 # path unchanged but evicted → wasted send
    evictions: int = 0

    @property
    def forwards(self):
        return self.necessary_forwards + self.redundant_forwards

    @property
    def suppression_rate(self):
        return self.hits / self.total if self.total else 0.0

    @property
    def forward_rate(self):
        return self.forwards / self.total if self.total else 0.0

    @property
    def redundancy_rate(self):
        """Fraction of all forwards that were unnecessary (eviction overhead)."""
        return self.redundant_forwards / self.forwards if self.forwards else 0.0

    @property
    def efficiency(self):
        """Fraction of forwards that were necessary."""
        return self.necessary_forwards / self.forwards if self.forwards else 1.0

    def __str__(self):
        cap = f"{self.capacity}" if self.capacity != float('inf') else "∞"
        return (
            f"{self.cache_name:<22} cap={cap:<6} "
            f"total={self.total:>7,}  "
            f"suppressed={self.hits:>7,} ({100*self.suppression_rate:5.1f}%)  "
            f"forwarded={self.forwards:>7,} ({100*self.forward_rate:5.1f}%)  "
            f"new={self.new_route_forwards:>6,}  "
            f"chg={self.route_change_forwards:>6,}  "
            f"redundant={self.redundant_forwards:>6,} ({100*self.redundancy_rate:5.1f}% of fwds)  "
            f"evictions={self.evictions:>6,}"
        )


def cache_slots_used(cache):
    """Best-effort occupancy introspection across cache policy implementations."""
    if hasattr(cache, '_store') and isinstance(cache._store, (dict, OrderedDict)):  # pyright: ignore[reportAttributeAccessIssue]
        return len(cache._store)  # pyright: ignore[reportAttributeAccessIssue]

    if hasattr(cache, '_protected') and hasattr(cache, '_probation'):
        protected = getattr(cache, '_protected')
        probation = getattr(cache, '_probation')
        if isinstance(protected, (dict, OrderedDict)) and isinstance(probation, (dict, OrderedDict)):
            return len(protected) + len(probation)

    if hasattr(cache, '_sets'):
        sets_obj = getattr(cache, '_sets')
        if isinstance(sets_obj, list):
            total = 0
            for bucket in sets_obj:
                if isinstance(bucket, list):
                    total += len(bucket)
            return total

    return None


# ---------------------------------------------------------------------------
# Cache implementations
# ---------------------------------------------------------------------------

class InfiniteLastPath:
    """Oracle — unbounded LRU: stores last_path per flow, never evicts."""
    name = "Infinite"
    capacity = float('inf')

    def __init__(self):
        self._store = {}  # flow_id -> last_path tuple

    def lookup_and_update(self, flow, path, ts=0):
        """
        Returns (hit: bool, eviction: bool).
        hit=True  → suppress (path matches last forwarded path for this flow)
        hit=False → forward (new flow or path changed)
        """
        last = self._store.get(flow)
        self._store[flow] = path
        if last is None:
            return False, False
        return last == path, False


class LRULastPath:
    """
    Bounded LRU cache.  N slots, one per flow, stores last_path.
    Eviction of a flow means its path is forgotten; the next packet for
    that flow will be a miss (possibly redundant).
    """
    name = "LRU"

    def __init__(self, capacity):
        self.capacity = capacity
        # OrderedDict: flow_id -> last_path tuple   (MRU at end)
        self._store = OrderedDict()

    def lookup_and_update(self, flow, path, ts=0):
        evicted = False
        if flow in self._store:
            old = self._store[flow]
            self._store.move_to_end(flow)
            self._store[flow] = path
            hit = (old == path)
            return hit, False
        # flow not in cache
        if len(self._store) >= self.capacity:
            self._store.popitem(last=False)  # evict LRU
            evicted = True
        self._store[flow] = path
        return False, evicted  # miss


class FIFOLastPath:
    """
    Bounded FIFO cache.  N slots.  Evicts in insertion order regardless of
    access frequency.
    """
    name = "FIFO"

    def __init__(self, capacity):
        self.capacity = capacity
        self._store = {}          # flow_id -> last_path
        self._order = deque()     # insertion order (flow_ids)

    def lookup_and_update(self, flow, path, ts=0):
        evicted = False
        if flow in self._store:
            old = self._store[flow]
            self._store[flow] = path  # update in place, keep FIFO order
            return (old == path), False
        # not in cache
        if len(self._store) >= self.capacity:
            victim = self._order.popleft()
            del self._store[victim]
            evicted = True
        self._store[flow] = path
        self._order.append(flow)
        return False, evicted


class RollingBloomFilter:
    """
    Rotating 2-window Bloom filter with deterministic hashes.

    Membership is checked against current and previous windows to provide
    lightweight time-decay without storing exact keys.
    """

    def __init__(self, bits=1 << 18, hashes=4):
        if bits <= 0:
            raise ValueError("bits must be > 0")
        if hashes <= 0:
            raise ValueError("hashes must be > 0")
        self.bits = bits
        self.hashes = hashes
        self._current = bytearray((bits + 7) // 8)
        self._previous = bytearray((bits + 7) // 8)

    def reset_epoch(self):
        self._previous = self._current
        self._current = bytearray((self.bits + 7) // 8)

    def _bit_get(self, arr, idx):
        return (arr[idx >> 3] >> (idx & 7)) & 1

    def _bit_set(self, arr, idx):
        arr[idx >> 3] |= (1 << (idx & 7))

    def _hash_positions(self, key):
        b = str(key).encode("ascii")
        d1 = hashlib.blake2b(b, digest_size=8, person=b"tbloom1").digest()
        d2 = hashlib.blake2b(b, digest_size=8, person=b"tbloom2").digest()
        h1 = int.from_bytes(d1, "little")
        h2 = int.from_bytes(d2, "little") or 1
        for i in range(self.hashes):
            yield (h1 + i * h2) % self.bits

    def add(self, key):
        for pos in self._hash_positions(key):
            self._bit_set(self._current, pos)

    def contains(self, key):
        for pos in self._hash_positions(key):
            if not (self._bit_get(self._current, pos) or self._bit_get(self._previous, pos)):
                return False
        return True


class LRULastPathTTL:
    """
    LRU cache with a time-to-live (TTL) per entry.

    A lookup is a HIT only if the path matches AND the entry is fresh
    (current_ts - last_forwarded_ts < ttl_ps).  If the TTL has expired
    the packet is forwarded even if the path hasn't changed — keep-alive.

    Timestamps come from the last hop's 'ts' field in the INT record
    (picoseconds, matching the simulator clock).

    Key tradeoff vs LRULastPath:
      + Guarantees the collector hears from every active flow at least once
        per TTL window regardless of path stability.
      - Extra forwards for long-lived stable flows (keep-alive overhead).
    """
    name = "LRUTTL"

    def __init__(self, capacity, ttl_ps=10_000_000_000):
        self.capacity = capacity
        self.ttl_ps = ttl_ps
        # OrderedDict: flow_id -> (last_path, last_forward_ts)
        self._store = OrderedDict()

    def lookup_and_update(self, flow, path, ts=0):
        evicted = False
        if flow in self._store:
            old_path, last_ts = self._store[flow]
            self._store.move_to_end(flow)
            if old_path == path and (ts - last_ts) < self.ttl_ps:
                return True, False   # hit: same path, still fresh
            # miss: path changed OR TTL expired
            self._store[flow] = (path, ts)
            return False, False
        # new flow
        if len(self._store) >= self.capacity:
            self._store.popitem(last=False)
            evicted = True
        self._store[flow] = (path, ts)
        return False, evicted

class FreshnessInvalidationLRU:
    """
    LRU cache with hard freshness invalidation.

    If an entry is older than freshness_ttl_ps at lookup time, it is removed
    from cache before processing the packet. The packet is then treated as a
    miss and forwarded. This models stale-cache invalidation behavior where
    old metadata is discarded instead of being refreshed in place.
    """
    name = "FreshnessInvalidationLRU"

    def __init__(self, capacity, freshness_ttl_ps=2_000_000_000):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        if freshness_ttl_ps <= 0:
            raise ValueError("freshness_ttl_ps must be > 0")
        self.capacity = capacity
        self.freshness_ttl_ps = freshness_ttl_ps
        # OrderedDict: flow_id -> (last_path, last_seen_ts)
        self._store = OrderedDict()

    def lookup_and_update(self, flow, path, ts=0):
        evicted = False
        if flow in self._store:
            old_path, old_ts = self._store[flow]
            age = ts - old_ts
            if age >= self.freshness_ttl_ps:
                # Hard invalidation of stale entry.
                del self._store[flow]
            else:
                self._store.move_to_end(flow)
                self._store[flow] = (path, ts)
                return (old_path == path), False

        if len(self._store) >= self.capacity:
            self._store.popitem(last=False)
            evicted = True
        self._store[flow] = (path, ts)
        return False, evicted


class DualFreshnessLRU:
    """
    LRU with dual freshness classes (time-variant vs static).

    - Time-variant flows use dynamic_ttl_ps (short freshness window).
    - Once a flow is stable for stable_hit_threshold consecutive hits,
      it transitions to static class and uses static_ttl_ps (long window).
    - Any path change resets it back to time-variant class.

    This approximates Cache-INT's differentiated handling of frequently-changing
    vs stable state without introducing control-plane path planning.
    """
    name = "DualFreshnessLRU"

    def __init__(
        self,
        capacity,
        dynamic_ttl_ps=500_000_000,
        static_ttl_ps=10_000_000_000,
        stable_hit_threshold=3,
    ):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        if dynamic_ttl_ps <= 0 or static_ttl_ps <= 0:
            raise ValueError("dynamic_ttl_ps and static_ttl_ps must be > 0")
        if stable_hit_threshold <= 0:
            raise ValueError("stable_hit_threshold must be > 0")
        self.capacity = capacity
        self.dynamic_ttl_ps = dynamic_ttl_ps
        self.static_ttl_ps = static_ttl_ps
        self.stable_hit_threshold = stable_hit_threshold
        # OrderedDict: flow_id -> (last_path, last_forward_ts, stable_hits)
        self._store = OrderedDict()

    def lookup_and_update(self, flow, path, ts=0):
        evicted = False
        if flow in self._store:
            old_path, last_ts, stable_hits = self._store[flow]
            ttl = self.static_ttl_ps if stable_hits >= self.stable_hit_threshold else self.dynamic_ttl_ps
            self._store.move_to_end(flow)

            if old_path == path and (ts - last_ts) < ttl:
                stable_hits = min(stable_hits + 1, self.stable_hit_threshold)
                self._store[flow] = (old_path, last_ts, stable_hits)
                return True, False

            if old_path == path:
                stable_hits = min(stable_hits + 1, self.stable_hit_threshold)
            else:
                stable_hits = 0
            self._store[flow] = (path, ts, stable_hits)
            return False, False

        if len(self._store) >= self.capacity:
            self._store.popitem(last=False)
            evicted = True
        self._store[flow] = (path, ts, 0)
        return False, evicted


class LFULastPath:
    """
    Bounded LFU (Least Frequently Used) cache.  N slots, stores last path.

    Evicts the flow that has been referenced the fewest times total.
    Contrasts with LRU on the recency vs frequency axis.

    In INT telemetry, long-lived active flows accumulate high reference counts
    and are protected from eviction.  Short-lived or recently-started flows
    are more likely to be evicted during congestion.

    O(log N) eviction using a lazy-deletion min-heap keyed on (freq, seq).
    Stale heap entries (freq changed since push) are discarded on pop.
    """
    name = "LFU"

    def __init__(self, capacity):
        self.capacity = capacity
        self._store   = {}   # flow_id -> last_path
        self._freq    = {}   # flow_id -> reference count
        self._seq_of  = {}   # flow_id -> seq when last pushed to heap
        self._heap    = []   # min-heap of (freq, seq, flow_id)
        self._seq     = 0

    def _evict_one(self):
        # Pop stale entries until we find one that matches current freq+seq
        while self._heap:
            freq, seq, flow = heapq.heappop(self._heap)
            if flow in self._store and self._freq[flow] == freq and self._seq_of[flow] == seq:
                del self._store[flow]
                del self._freq[flow]
                del self._seq_of[flow]
                return

    def lookup_and_update(self, flow, path, ts=0):
        evicted = False
        if flow in self._store:
            old = self._store[flow]
            self._freq[flow] += 1
            # Push updated entry; old heap entry becomes stale (lazy delete)
            self._seq += 1
            self._seq_of[flow] = self._seq
            heapq.heappush(self._heap, (self._freq[flow], self._seq, flow))
            self._store[flow] = path
            return (old == path), False
        # new flow
        if len(self._store) >= self.capacity:
            self._evict_one()
            evicted = True
        self._seq += 1
        self._store[flow]   = path
        self._freq[flow]    = 1
        self._seq_of[flow]  = self._seq
        heapq.heappush(self._heap, (1, self._seq, flow))
        return False, evicted


class VolatilityAwareLRU:
    """
    Bounded cache that evicts the most path-VOLATILE flow first.

    Domain motivation: a stable flow (path never changes) generates 100%
    cache hits and evicting it converts all its traffic to redundant forwards.
    A volatile flow (path changes every path_burst packets) has some fraction
    of packets that would be necessary forwards regardless of whether it is
    in cache; evicting it costs fewer *extra* (redundant) forwards than
    evicting a stable flow.

    Each slot stores: last_path, lru_position.
    A global (unbounded) change-count dict persists across evictions so that
    volatile flows accumulate a high count even if they were recently evicted
    and re-admitted — avoiding the cold-start problem where counts at at
    zero on every re-entry.
    Eviction target: flow with most path changes (most volatile), LRU tiebreaker.

    O(log N) eviction using a lazy-deletion max-heap (negated changes) keyed
    on (-changes, lru_seq).  Stale heap entries are discarded on pop.
    """
    name = "VolatilityAwareLRU"

    def __init__(self, capacity):
        self.capacity  = capacity
        self._store    = {}   # flow_id -> last_path  (in-cache only)
        self._changes  = {}   # flow_id -> total path-change count (persists)
        self._heap_key = {}   # flow_id -> (neg_changes, lru_seq) when last pushed
        self._heap     = []   # min-heap of (neg_changes, lru_seq, flow_id)
        self._seq      = 0

    def _push(self, flow):
        neg_c = -self._changes.get(flow, 0)
        key = (neg_c, self._seq)
        self._heap_key[flow] = key
        heapq.heappush(self._heap, (neg_c, self._seq, flow))

    def _evict_one(self):
        # Pop until we find a live, non-stale entry
        while self._heap:
            neg_c, seq, flow = heapq.heappop(self._heap)
            if flow in self._store and self._heap_key.get(flow) == (neg_c, seq):
                del self._store[flow]
                del self._heap_key[flow]
                # _changes[flow] kept for future re-admissions
                return

    def lookup_and_update(self, flow, path, ts=0):
        evicted = False
        self._seq += 1
        if flow in self._store:
            old = self._store[flow]
            if old != path:
                self._changes[flow] = self._changes.get(flow, 0) + 1
                self._store[flow] = path
                # Push updated heap entry; old becomes stale
                self._push(flow)
                return False, False  # miss: path changed
            # hit: refresh LRU position in heap
            self._push(flow)
            return True, False
        # new or re-admitted flow
        if len(self._store) >= self.capacity:
            self._evict_one()
            evicted = True
        self._store[flow] = path
        if flow not in self._changes:
            self._changes[flow] = 0
        self._push(flow)
        return False, evicted


class AdmissionFilterLRU:
    """
    One-hit-wonder admission control.

    This is the cache-on-second-hit rule described in the Akamai survey paper:
    on the first encounter a flow is recorded in a Bloom filter and forwarded;
    on the second encounter within the recent window it is admitted to the LRU
    cache.  The Bloom filter is periodically refreshed so the notion of
    "recent" follows the current access stream rather than unbounded history.

    Key tradeoff vs plain LRU:
      + Protects main cache slots from one-shot / short-lived flows
      + Reduces write churn by bypassing the first encounter
      - Second encounter required before cache admission
      - Bloom false positives can admit a few borderline flows early
    """
    name = "OneHitWonderLRU"

    def __init__(self, capacity, pending_size=None, pending_reset_every=0,
                 bloom_bits=1 << 18, bloom_hashes=4):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        self.capacity = capacity
        self._epoch = pending_reset_every
        self._ops = 0
        self._seen = RollingBloomFilter(bits=bloom_bits, hashes=bloom_hashes)
        self._store   = OrderedDict()  # admitted flows: flow_id -> last_path  (LRU)

    def _tick(self):
        self._ops += 1
        if self._epoch > 0 and self._ops % self._epoch == 0:
            self._seen.reset_epoch()

    def lookup_and_update(self, flow, path, ts=0):
        self._tick()
        evicted = False

        # --- Already admitted to main cache ---
        if flow in self._store:
            old = self._store[flow]
            self._store.move_to_end(flow)
            self._store[flow] = path
            return (old == path), False

        seen_recently = self._seen.contains(flow)
        self._seen.add(flow)

        if not seen_recently:
            return False, False

        if len(self._store) >= self.capacity:
            self._store.popitem(last=False)
            evicted = True
        self._store[flow] = path
        return False, evicted


class PendingAdmissionLRU:
    """
    LRU with exact second-touch admission (legacy admission baseline).

    This is the pre-Bloom admission filter implementation used previously in
    this repo: first touch stores flow state in a bounded FIFO pending table;
    second touch admits to the main LRU cache.
    """
    name = "PendingAdmissionLRU"

    def __init__(self, capacity, pending_size=None, pending_reset_every=0):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        self.capacity = capacity
        self._pending_cap = pending_size if pending_size is not None else capacity
        if self._pending_cap <= 0:
            raise ValueError("pending_size must be > 0")
        self._pending_reset_every = pending_reset_every
        self._ops = 0
        self._store = OrderedDict()  # admitted flows: flow_id -> last_path (LRU)
        self._pending = OrderedDict()  # pending flows: flow_id -> first_path (FIFO)

    def lookup_and_update(self, flow, path, ts=0):
        evicted = False
        self._ops += 1
        if self._pending_reset_every and self._ops % self._pending_reset_every == 0:
            self._pending.clear()

        if flow in self._store:
            old = self._store[flow]
            self._store.move_to_end(flow)
            self._store[flow] = path
            return (old == path), False

        if flow in self._pending:
            old = self._pending.pop(flow)
            if len(self._store) >= self.capacity:
                self._store.popitem(last=False)
                evicted = True
            self._store[flow] = path
            return (old == path), evicted

        if len(self._pending) >= self._pending_cap:
            self._pending.popitem(last=False)
        self._pending[flow] = path
        return False, False


class PITCollapsedLRU:
    """
    LRU cache with Pending-Interest-Table style collapsed forwarding.

    Behavior:
      - On miss, create an inflight PIT entry and forward exactly one request.
      - While inflight and before response arrival, same (flow,path) requests are
        collapsed (suppressed) by PIT.
      - When download delay elapses, content is admitted to cache and PIT entry
        is cleared.

    This approximates the PIT semantics studied in the PIT cache paper with a
    fixed per-object download delay in picoseconds.
    """
    name = "PITCollapsedLRU"

    def __init__(self, capacity, download_delay_ps=2_000_000, pit_capacity=None):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        if download_delay_ps <= 0:
            raise ValueError("download_delay_ps must be > 0")
        if pit_capacity is None:
            pit_capacity = capacity
        if pit_capacity <= 0:
            raise ValueError("pit_capacity must be > 0")
        self.capacity = capacity
        self.download_delay_ps = download_delay_ps
        self.pit_capacity = pit_capacity
        self._store = OrderedDict()  # flow -> last_path
        # Keep PIT state bounded so auxiliary memory does not dominate cache size.
        self._pit = OrderedDict()  # flow -> (pending_path, ready_ts)

    def _admit(self, flow, path):
        evicted = False
        if len(self._store) >= self.capacity:
            self._store.popitem(last=False)
            evicted = True
        self._store[flow] = path
        return evicted

    def lookup_and_update(self, flow, path, ts=0):
        evicted = False

        if flow in self._pit:
            pending_path, ready_ts = self._pit[flow]
            if ts < ready_ts and pending_path == path:
                self._pit.move_to_end(flow)
                return True, False
            if ts >= ready_ts:
                evicted = self._admit(flow, pending_path)
                del self._pit[flow]
            elif pending_path != path:
                self._pit[flow] = (path, ts + self.download_delay_ps)
                self._pit.move_to_end(flow)
                return False, False

        if flow in self._store:
            old = self._store[flow]
            self._store.move_to_end(flow)
            self._store[flow] = path
            return (old == path), evicted

        if len(self._pit) >= self.pit_capacity:
            self._pit.popitem(last=False)
        self._pit[flow] = (path, ts + self.download_delay_ps)
        return False, evicted


class AdaptiveAdmissionLRU:
    """
    OneHitWonderLRU with pressure-adaptive bypass.

    While eviction pressure is low, new flows are admitted immediately
    (LRU-like behavior) to avoid unnecessary cold-start misses.
    Under sustained eviction pressure, policy switches to second-chance
    admission (pending sketch) to protect cache slots from one-hit flows.
    """
    name = "AdaptiveAdmissionLRU"

    def __init__(self, capacity, pending_size=None, pending_reset_every=0,
                 pressure_window=10000, eviction_high_watermark=0.02):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        if pressure_window <= 0:
            raise ValueError("pressure_window must be > 0")
        self.capacity = capacity
        self._pending_cap = pending_size if pending_size is not None else capacity
        if self._pending_cap <= 0:
            raise ValueError("pending_size must be > 0")
        self._pending_reset_every = pending_reset_every
        self._ops = 0

        self._pressure_window = pressure_window
        self._evict_high_watermark = eviction_high_watermark
        self._window_ops = 0
        self._window_evicts = 0
        self._under_pressure = False

        self._store = OrderedDict()    # admitted flows: flow_id -> last_path (LRU)
        self._pending = OrderedDict()  # pending flows: flow_id -> first_path (FIFO)

    def _update_pressure(self, evicted):
        self._window_ops += 1
        if evicted:
            self._window_evicts += 1
        if self._window_ops >= self._pressure_window:
            ratio = self._window_evicts / self._window_ops
            self._under_pressure = ratio >= self._evict_high_watermark
            self._window_ops = 0
            self._window_evicts = 0

    def lookup_and_update(self, flow, path, ts=0):
        evicted = False
        self._ops += 1
        if self._pending_reset_every and self._ops % self._pending_reset_every == 0:
            self._pending.clear()

        if flow in self._store:
            old = self._store[flow]
            self._store.move_to_end(flow)
            self._store[flow] = path
            self._update_pressure(False)
            return (old == path), False

        # Low pressure: bypass filter and admit directly (LRU behavior).
        if not self._under_pressure:
            if len(self._store) >= self.capacity:
                self._store.popitem(last=False)
                evicted = True
            self._store[flow] = path
            self._update_pressure(evicted)
            return False, evicted

        # High pressure: fall back to second-chance admission.
        if flow in self._pending:
            old = self._pending.pop(flow)
            if len(self._store) >= self.capacity:
                self._store.popitem(last=False)
                evicted = True
            self._store[flow] = path
            self._update_pressure(evicted)
            return (old == path), evicted

        if len(self._pending) >= self._pending_cap:
            self._pending.popitem(last=False)
        self._pending[flow] = path
        self._update_pressure(False)
        return False, False


class OnlineAdaptiveAdmissionLRU:
    """
    Online adaptive admission controller.

    The policy changes admission strictness during runtime using local signals:
      - eviction ratio in recent windows
      - hit ratio in recent windows

    Modes:
      0: open admission (LRU-like)
      1: second-touch admission
      2: third-touch admission
    """
    name = "OnlineAdaptiveAdmissionLRU"

    def __init__(
        self,
        capacity,
        pending_size=None,
        pressure_window=10000,
        high_evict=0.03,
        low_evict=0.005,
        weak_hit=0.70,
        strong_hit=0.92,
    ):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        if pressure_window <= 0:
            raise ValueError("pressure_window must be > 0")
        self.capacity = capacity
        self._pending_cap = pending_size if pending_size is not None else capacity
        if self._pending_cap <= 0:
            raise ValueError("pending_size must be > 0")

        self._store = OrderedDict()     # admitted: flow -> last_path
        self._pending = OrderedDict()   # pending: flow -> (last_path, touches)

        self._mode = 0
        self._pressure_window = pressure_window
        self._high_evict = high_evict
        self._low_evict = low_evict
        self._weak_hit = weak_hit
        self._strong_hit = strong_hit

        self._w_ops = 0
        self._w_hits = 0
        self._w_evicts = 0

    def _bump_window(self, hit, evicted):
        self._w_ops += 1
        if hit:
            self._w_hits += 1
        if evicted:
            self._w_evicts += 1

        if self._w_ops < self._pressure_window:
            return

        hit_ratio = self._w_hits / self._w_ops
        evict_ratio = self._w_evicts / self._w_ops

        if evict_ratio >= self._high_evict and hit_ratio <= self._weak_hit:
            self._mode = min(2, self._mode + 1)
        elif evict_ratio <= self._low_evict and hit_ratio >= self._strong_hit:
            self._mode = max(0, self._mode - 1)

        self._w_ops = 0
        self._w_hits = 0
        self._w_evicts = 0

    def lookup_and_update(self, flow, path, ts=0):
        evicted = False

        if flow in self._store:
            old = self._store[flow]
            self._store.move_to_end(flow)
            self._store[flow] = path
            hit = (old == path)
            self._bump_window(hit, False)
            return hit, False

        # Mode 0: open admission, behave as plain LRU on misses.
        if self._mode == 0:
            if len(self._store) >= self.capacity:
                self._store.popitem(last=False)
                evicted = True
            self._store[flow] = path
            self._bump_window(False, evicted)
            return False, evicted

        prev_path, touches = self._pending.pop(flow, (path, 0))
        touches += 1

        required_touches = 1 if self._mode == 1 else 2
        if touches <= required_touches:
            if len(self._pending) >= self._pending_cap:
                self._pending.popitem(last=False)
            self._pending[flow] = (path, touches)
            self._bump_window(False, False)
            return False, False

        if len(self._store) >= self.capacity:
            self._store.popitem(last=False)
            evicted = True
        self._store[flow] = path
        hit = (prev_path == path)
        self._bump_window(hit, evicted)
        return hit, evicted


class OnlineAdaptiveDualTTL:
    """
    Dual-freshness LRU with online dynamic-TTL adaptation.

    Static flows keep a long TTL, while dynamic flows use a short TTL that is
    continuously tuned based on observed stale-expiry pressure and eviction rate.
    """
    name = "OnlineAdaptiveDualTTL"

    def __init__(
        self,
        capacity,
        dynamic_ttl_ps=500_000_000,
        static_ttl_ps=10_000_000_000,
        min_dynamic_ttl_ps=100_000_000,
        max_dynamic_ttl_ps=20_000_000_000,
        stable_hit_threshold=3,
        adapt_window=5000,
    ):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        if stable_hit_threshold <= 0:
            raise ValueError("stable_hit_threshold must be > 0")
        if min_dynamic_ttl_ps <= 0 or max_dynamic_ttl_ps <= 0:
            raise ValueError("dynamic TTL bounds must be > 0")
        if min_dynamic_ttl_ps > max_dynamic_ttl_ps:
            raise ValueError("min_dynamic_ttl_ps must be <= max_dynamic_ttl_ps")
        if adapt_window <= 0:
            raise ValueError("adapt_window must be > 0")

        self.capacity = capacity
        self.static_ttl_ps = static_ttl_ps
        self.min_dynamic_ttl_ps = min_dynamic_ttl_ps
        self.max_dynamic_ttl_ps = max_dynamic_ttl_ps
        self.dynamic_ttl_ps = max(min_dynamic_ttl_ps, min(dynamic_ttl_ps, max_dynamic_ttl_ps))
        self.stable_hit_threshold = stable_hit_threshold
        self.adapt_window = adapt_window

        # flow -> (last_path, last_seen_ts, stable_hits)
        self._store = OrderedDict()

        self._w_ops = 0
        self._w_stale = 0
        self._w_evict = 0
        self._w_hits = 0

    def _adapt(self):
        if self._w_ops < self.adapt_window:
            return

        stale_ratio = self._w_stale / self._w_ops
        evict_ratio = self._w_evict / self._w_ops
        hit_ratio = self._w_hits / self._w_ops

        if stale_ratio > 0.20 and evict_ratio < 0.05:
            self.dynamic_ttl_ps = min(
                self.max_dynamic_ttl_ps,
                int(self.dynamic_ttl_ps * 1.25),
            )
        elif evict_ratio > 0.20 and hit_ratio < 0.80:
            self.dynamic_ttl_ps = max(
                self.min_dynamic_ttl_ps,
                int(self.dynamic_ttl_ps * 0.80),
            )

        self._w_ops = 0
        self._w_stale = 0
        self._w_evict = 0
        self._w_hits = 0

    def lookup_and_update(self, flow, path, ts=0):
        evicted = False
        stale_expired = False

        if flow in self._store:
            old_path, last_ts, stable_hits = self._store[flow]
            ttl = self.static_ttl_ps if stable_hits >= self.stable_hit_threshold else self.dynamic_ttl_ps
            self._store.move_to_end(flow)

            age = ts - last_ts
            if old_path == path and age < ttl:
                stable_hits = min(stable_hits + 1, self.stable_hit_threshold)
                self._store[flow] = (old_path, last_ts, stable_hits)
                self._w_ops += 1
                self._w_hits += 1
                self._adapt()
                return True, False

            if old_path == path and age >= ttl:
                stale_expired = True

            if old_path == path:
                stable_hits = min(stable_hits + 1, self.stable_hit_threshold)
            else:
                stable_hits = 0
            self._store[flow] = (path, ts, stable_hits)
            self._w_ops += 1
            if stale_expired:
                self._w_stale += 1
            self._adapt()
            return False, False

        if len(self._store) >= self.capacity:
            self._store.popitem(last=False)
            evicted = True
        self._store[flow] = (path, ts, 0)

        self._w_ops += 1
        if evicted:
            self._w_evict += 1
        self._adapt()
        return False, evicted


class FlowLifetimeAdaptiveTTL:
    """
    LRU with per-flow adaptive freshness windows.

    Each flow tracks an EMA of inter-arrival gap in picoseconds. The flow TTL is
    derived from this EMA and clamped to configurable bounds:

      ttl(flow) = clamp(ttl_multiplier * ema_gap(flow), min_ttl_ps, max_ttl_ps)

    Intuition:
      - Fast/short-lived flows keep short TTLs.
      - Slower/long-lived flows keep longer TTLs.

    This is an explicit "lifetime-aware freshness" policy without requiring an
    external control loop.
    """
    name = "FlowLifetimeAdaptiveTTL"

    def __init__(
        self,
        capacity,
        min_ttl_ps=100_000_000,
        max_ttl_ps=20_000_000_000,
        ema_alpha=0.2,
        ttl_multiplier=4.0,
    ):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        if min_ttl_ps <= 0 or max_ttl_ps <= 0:
            raise ValueError("TTL values must be > 0")
        if min_ttl_ps > max_ttl_ps:
            raise ValueError("min_ttl_ps must be <= max_ttl_ps")
        if not (0.0 < ema_alpha <= 1.0):
            raise ValueError("ema_alpha must be in (0, 1]")
        if ttl_multiplier <= 0.0:
            raise ValueError("ttl_multiplier must be > 0")

        self.capacity = capacity
        self.min_ttl_ps = min_ttl_ps
        self.max_ttl_ps = max_ttl_ps
        self.ema_alpha = ema_alpha
        self.ttl_multiplier = ttl_multiplier

        # flow -> (last_path, last_seen_ts, ema_gap_ps, samples)
        self._store = OrderedDict()

    def _effective_ttl(self, ema_gap_ps, samples):
        if samples <= 1:
            # No gap observed yet — never expire on first return (pure LRU behaviour
            # until we have data to learn from)
            return float('inf')
        ttl = int(ema_gap_ps * self.ttl_multiplier)
        if ttl < self.min_ttl_ps:
            return self.min_ttl_ps
        if ttl > self.max_ttl_ps:
            return self.max_ttl_ps
        return ttl

    def _update_ema(self, prev_ema, gap_ps, samples):
        gap_ps = max(0, int(gap_ps))
        if samples <= 1:
            return gap_ps
        return int(self.ema_alpha * gap_ps + (1.0 - self.ema_alpha) * prev_ema)

    def lookup_and_update(self, flow, path, ts=0):
        evicted = False

        if flow in self._store:
            old_path, last_ts, ema_gap_ps, samples = self._store[flow]
            age = max(0, int(ts - last_ts))
            ttl_ps = self._effective_ttl(ema_gap_ps, samples)

            self._store.move_to_end(flow)
            hit = (old_path == path) and (age < ttl_ps)

            samples = samples + 1
            ema_gap_ps = self._update_ema(ema_gap_ps, age, samples)
            self._store[flow] = (path, ts, ema_gap_ps, samples)
            return hit, False

        if len(self._store) >= self.capacity:
            self._store.popitem(last=False)
            evicted = True

        self._store[flow] = (path, ts, 0, 1)
        return False, evicted


class TimingBloomLRU:
    """
    LRU cache with timing Bloom admission.

    A new flow is admitted only if its ID appears in the recent 2-window Bloom
    history. Otherwise it is bypassed and recorded in the current Bloom window.
    """
    name = "TimeLimitedBloomLRU"

    def __init__(self, capacity, bloom_bits=1 << 18, bloom_hashes=4, bloom_epoch_records=256,
                 pressure_window=10000, eviction_high_watermark=0.02):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        if bloom_epoch_records <= 0:
            raise ValueError("bloom_epoch_records must be > 0")
        if pressure_window <= 0:
            raise ValueError("pressure_window must be > 0")
        self.capacity = capacity
        self._store = OrderedDict()  # flow_id -> last_path
        self._bloom = RollingBloomFilter(bits=bloom_bits, hashes=bloom_hashes)
        self._epoch = bloom_epoch_records
        self._ops = 0
        self._pressure_window = pressure_window
        self._evict_high_watermark = eviction_high_watermark
        self._window_ops = 0
        self._window_evicts = 0
        self._under_pressure = False

    def _tick(self):
        self._ops += 1
        if self._ops % self._epoch == 0:
            self._bloom.reset_epoch()

    def _update_pressure(self, evicted):
        self._window_ops += 1
        if evicted:
            self._window_evicts += 1
        if self._window_ops >= self._pressure_window:
            ratio = self._window_evicts / self._window_ops
            self._under_pressure = ratio >= self._evict_high_watermark
            self._window_ops = 0
            self._window_evicts = 0

    def lookup_and_update(self, flow, path, ts=0):
        self._tick()
        evicted = False
        if flow in self._store:
            old = self._store[flow]
            self._store.move_to_end(flow)
            self._store[flow] = path
            self._update_pressure(False)
            return (old == path), False

        seen_recently = self._bloom.contains(flow)
        self._bloom.add(flow)
        gate_admission = (len(self._store) >= self.capacity) and self._under_pressure
        if gate_admission and not seen_recently:
            self._update_pressure(False)
            return False, False

        if len(self._store) >= self.capacity:
            self._store.popitem(last=False)
            evicted = True
        self._store[flow] = path
        self._update_pressure(evicted)
        return False, evicted


class TwoFilterOHWLRU:
    """
    Akamai-style one-hit-wonder guard using two timing Bloom filters.

    New flow IDs progress through two filters before admission:
      unseen -> filter1
      seen in filter1 -> filter2
      seen in filter2 -> admit to LRU
    """
    name = "TwoFilterOHWLRU"

    def __init__(self, capacity, bloom_bits=1 << 18, bloom_hashes=4, bloom_epoch_records=256,
                 pressure_window=10000, eviction_high_watermark=0.02):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        if bloom_epoch_records <= 0:
            raise ValueError("bloom_epoch_records must be > 0")
        if pressure_window <= 0:
            raise ValueError("pressure_window must be > 0")
        self.capacity = capacity
        self._store = OrderedDict()  # flow_id -> last_path
        self._f1 = RollingBloomFilter(bits=bloom_bits, hashes=bloom_hashes)
        self._f2 = RollingBloomFilter(bits=bloom_bits, hashes=bloom_hashes)
        self._epoch = bloom_epoch_records
        self._ops = 0
        self._pressure_window = pressure_window
        self._evict_high_watermark = eviction_high_watermark
        self._window_ops = 0
        self._window_evicts = 0
        self._under_pressure = False

    def _tick(self):
        self._ops += 1
        if self._ops % self._epoch == 0:
            self._f1.reset_epoch()
            self._f2.reset_epoch()

    def _update_pressure(self, evicted):
        self._window_ops += 1
        if evicted:
            self._window_evicts += 1
        if self._window_ops >= self._pressure_window:
            ratio = self._window_evicts / self._window_ops
            self._under_pressure = ratio >= self._evict_high_watermark
            self._window_ops = 0
            self._window_evicts = 0

    def lookup_and_update(self, flow, path, ts=0):
        self._tick()
        evicted = False
        if flow in self._store:
            old = self._store[flow]
            self._store.move_to_end(flow)
            self._store[flow] = path
            self._update_pressure(False)
            return (old == path), False

        in_f1 = self._f1.contains(flow)
        in_f2 = self._f2.contains(flow)
        if in_f1:
            self._f2.add(flow)
        else:
            self._f1.add(flow)

        gate_admission = (len(self._store) >= self.capacity) and self._under_pressure
        # Under pressure, require stronger evidence than TimingBloom:
        # the flow must have reached filter2 (seen across two gated checks).
        allow_admit = (not gate_admission) or in_f2
        if not allow_admit:
            self._update_pressure(False)
            return False, False

        if len(self._store) >= self.capacity:
            self._store.popitem(last=False)
            evicted = True
        self._store[flow] = path
        self._update_pressure(evicted)
        return False, evicted


class _TinyLFUSketch:
    """TinyLFU frequency sketch with reset aging and doorkeeper semantics."""

    def __init__(self, sample_size, counter_cap):
        if sample_size <= 0:
            raise ValueError("sample_size must be > 0")
        if counter_cap <= 0:
            raise ValueError("counter_cap must be > 0")
        self.sample_size = sample_size
        self.counter_cap = counter_cap
        self._ops = 0
        self._counts = {}
        self._doorkeeper = set()

    def _reset(self):
        new_counts = {}
        for key, value in self._counts.items():
            half = value // 2
            if half > 0:
                new_counts[key] = half
        self._counts = new_counts
        self._doorkeeper.clear()
        self._ops = 0

    def observe(self, key):
        self._ops += 1
        if key in self._doorkeeper:
            nxt = self._counts.get(key, 0) + 1
            self._counts[key] = min(nxt, self.counter_cap)
        else:
            self._doorkeeper.add(key)

        if self._ops >= self.sample_size:
            self._reset()

    def estimate(self, key):
        return self._counts.get(key, 0) + (1 if key in self._doorkeeper else 0)


class TinyLFULRU:
    """
    LRU eviction with TinyLFU admission.

    Policy behavior:
      - Maintains recency order only for admitted entries (LRU victim candidate).
      - Maintains an approximate TinyLFU frequency sketch over recent accesses.
      - On misses with full cache, compares candidate frequency to LRU victim
        frequency and only admits when candidate is more frequent.

    This follows the TinyLFU paper's admission-control spirit with a practical
    reset-aging sketch and doorkeeper front-end.
    """
    name = "TinyLFULRU"

    def __init__(self, capacity, sample_multiplier=8):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        if sample_multiplier <= 0:
            raise ValueError("sample_multiplier must be > 0")
        self.capacity = capacity
        self._store = OrderedDict()  # flow_id -> last_path
        sample_size = max(capacity, int(capacity * sample_multiplier))
        counter_cap = max(1, sample_size // capacity)
        self._sketch = _TinyLFUSketch(sample_size=sample_size, counter_cap=counter_cap)

    def lookup_and_update(self, flow, path, ts=0):
        self._sketch.observe(flow)

        if flow in self._store:
            old = self._store[flow]
            self._store.move_to_end(flow)
            self._store[flow] = path
            return (old == path), False

        if len(self._store) < self.capacity:
            self._store[flow] = path
            return False, False

        victim_flow = next(iter(self._store))
        if self._sketch.estimate(flow) > self._sketch.estimate(victim_flow):
            self._store.popitem(last=False)
            self._store[flow] = path
            return False, True

        # Candidate is bypassed (not admitted), cache state unchanged.
        return False, False


class _TinyCacheTable:
    """TinyCache-style fingerprint table with per-set bounded storage."""

    def __init__(self, set_count, set_capacity, duplicate_cap, fingerprint_bits=16, seed=0):
        if set_count <= 0:
            raise ValueError("set_count must be > 0")
        if set_capacity <= 0:
            raise ValueError("set_capacity must be > 0")
        if duplicate_cap <= 0:
            raise ValueError("duplicate_cap must be > 0")
        if fingerprint_bits <= 0:
            raise ValueError("fingerprint_bits must be > 0")
        self.set_count = set_count
        self.set_capacity = set_capacity
        self.duplicate_cap = duplicate_cap
        self.fingerprint_bits = fingerprint_bits
        self._mask = (1 << fingerprint_bits) - 1
        self._rng = random.Random(seed)
        self._sets = [[] for _ in range(set_count)]
        self._ops = 0
        self._sample_size = set_count * set_capacity

    def _fingerprint(self, key):
        digest = hashlib.blake2b(repr(key).encode("utf-8", errors="ignore"), digest_size=8, person=b"tinycach").digest()
        return int.from_bytes(digest, "little") & self._mask

    def _set_index(self, key):
        digest = hashlib.blake2b(repr(key).encode("utf-8", errors="ignore"), digest_size=8, person=b"tinycache").digest()
        return int.from_bytes(digest, "little") % self.set_count

    def _bucket_count(self, bucket, fingerprint):
        return sum(1 for item in bucket if item == fingerprint)

    def observe(self, key):
        fingerprint = self._fingerprint(key)
        set_idx = self._set_index(key)
        bucket = self._sets[set_idx]
        duplicate_count = self._bucket_count(bucket, fingerprint)

        if duplicate_count < self.duplicate_cap:
            if len(bucket) >= self.set_capacity:
                victim_idx = self._rng.randrange(len(bucket))
                bucket.pop(victim_idx)
            bucket.append(fingerprint)

        self._ops += 1
        if self._ops >= self._sample_size:
            self._ops = 0
            self._decay()

    def _decay(self):
        for idx, bucket in enumerate(self._sets):
            if not bucket:
                continue
            keep = []
            for fingerprint in bucket:
                if self._rng.random() < 0.5:
                    keep.append(fingerprint)
            self._sets[idx] = keep

    def estimate(self, key):
        fingerprint = self._fingerprint(key)
        bucket = self._sets[self._set_index(key)]
        return self._bucket_count(bucket, fingerprint)


class TinyCacheLRU:
    """
    LRU eviction with a TinyCache admission filter.

    TinyCache keeps a table of recent fingerprints and estimates frequency by
    counting matching fingerprints in the fingerprint's set. When the table is
    full, it evicts a random fingerprint from the same set as the new item.
    If the estimated frequency of the candidate is at least the victim's, the
    candidate is admitted and the LRU victim is displaced; otherwise it is
    bypassed.
    """
    name = "TinyCacheLRU"

    def __init__(self, capacity, sample_multiplier=8, set_count=None, duplicate_cap=None, fingerprint_bits=16):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        if sample_multiplier <= 0:
            raise ValueError("sample_multiplier must be > 0")
        self.capacity = capacity
        self._store = OrderedDict()  # flow_id -> last_path
        self._set_count = set_count if set_count is not None else max(1, capacity)
        self._set_capacity = max(1, sample_multiplier)
        self._duplicate_cap = duplicate_cap if duplicate_cap is not None else max(1, self._set_capacity // 2)
        self._table = _TinyCacheTable(
            set_count=self._set_count,
            set_capacity=self._set_capacity,
            duplicate_cap=self._duplicate_cap,
            fingerprint_bits=fingerprint_bits,
        )

    def lookup_and_update(self, flow, path, ts=0):
        self._table.observe(flow)

        if flow in self._store:
            old = self._store[flow]
            self._store.move_to_end(flow)
            self._store[flow] = path
            return (old == path), False

        if len(self._store) < self.capacity:
            self._store[flow] = path
            return False, False

        victim_flow = next(iter(self._store))
        if self._table.estimate(flow) >= self._table.estimate(victim_flow):
            self._store.popitem(last=False)
            self._store[flow] = path
            return False, True

        return False, False


class CacheINTFreshnessLRU:
    """
    Cache-INT inspired freshness cache.

    Adapts Cache-INT's core ideas to flow/path caching:
      - Classifies entries into dynamic (time-variant) vs static.
      - Dynamic entries use freshness invalidation (dynamic_ttl_ps).
      - Static entries do not expire by TTL.
      - On insert under pressure, evicts the least-fresh dynamic entry first.
      - Uses path hash checks to detect content changes and reset to dynamic.
    """
    name = "CacheINTFreshnessLRU"

    def __init__(self, capacity, dynamic_ttl_ps=500_000_000, stable_hit_threshold=3):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        if dynamic_ttl_ps <= 0:
            raise ValueError("dynamic_ttl_ps must be > 0")
        if stable_hit_threshold <= 0:
            raise ValueError("stable_hit_threshold must be > 0")
        self.capacity = capacity
        self.dynamic_ttl_ps = dynamic_ttl_ps
        self.stable_hit_threshold = stable_hit_threshold
        # flow -> dict(path, path_hash, last_update_ts, stable_hits, is_static)
        self._store = OrderedDict()

    def _path_hash(self, path):
        raw = repr(path).encode("ascii", errors="ignore")
        digest = hashlib.blake2b(raw, digest_size=8, person=b"cintpath").digest()
        return int.from_bytes(digest, "little")

    def _evict_one(self):
        victim = None
        victim_ts = None
        for flow, item in self._store.items():
            if item["is_static"]:
                continue
            ts = item["last_update_ts"]
            if victim is None or ts < victim_ts:
                victim = flow
                victim_ts = ts

        if victim is None:
            self._store.popitem(last=False)
            return
        del self._store[victim]

    def lookup_and_update(self, flow, path, ts=0):
        evicted = False
        new_hash = self._path_hash(path)

        if flow in self._store:
            item = self._store[flow]
            self._store.move_to_end(flow)
            same_path = (item["path_hash"] == new_hash and item["path"] == path)

            if same_path:
                item["stable_hits"] = min(item["stable_hits"] + 1, self.stable_hit_threshold)
                if item["stable_hits"] >= self.stable_hit_threshold:
                    item["is_static"] = True

                if item["is_static"]:
                    item["last_update_ts"] = ts
                    self._store[flow] = item
                    return True, False

                if (ts - item["last_update_ts"]) < self.dynamic_ttl_ps:
                    item["last_update_ts"] = ts
                    self._store[flow] = item
                    return True, False

                # Dynamic entry expired by freshness TTL.
                item["last_update_ts"] = ts
                self._store[flow] = item
                return False, False

            # Change detected: refresh content and demote to dynamic class.
            item["path"] = path
            item["path_hash"] = new_hash
            item["last_update_ts"] = ts
            item["stable_hits"] = 0
            item["is_static"] = False
            self._store[flow] = item
            return False, False

        if len(self._store) >= self.capacity:
            self._evict_one()
            evicted = True

        self._store[flow] = {
            "path": path,
            "path_hash": new_hash,
            "last_update_ts": ts,
            "stable_hits": 0,
            "is_static": False,
        }
        return False, evicted


class SegmentedLRU:
    """
    2-segment LRU (SLRU) cache.  Total N slots split into:
      - probation  (N//4 slots): new flows land here on first access
      - protected  (N - N//4 slots): flows that have been hit at least once

    On a hit in probation the flow is promoted to the MRU end of the protected
    segment.  If protected is full, its LRU entry is demoted back to the MRU
    end of probation before the promotion is applied — total occupancy stays N.
    On a probation miss (new flow) the LRU entry of probation is evicted; the
    protected segment is never disturbed by new arrivals.

    The effect: a flow must demonstrate value (be accessed twice without being
    evicted) before it is shielded from new-arrival churn.  Flows that are
    accessed only once stay in probation and are discarded cheaply without
    polluting the protected segment.  This is the same principle as the
    admission filter but achieved by triage *within* the cache rather than via
    a separate sketch, so total memory cost = N slots (not 2×N).

    Used in Linux page cache (inactive/active lists), many L2/L3 CPU caches,
    and MySQL's InnoDB buffer pool.
    """
    name = "SegmentedLRU"

    def __init__(self, capacity):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        self.capacity  = capacity
        self._prob_cap = max(1, capacity // 4)
        self._prot_cap = capacity - self._prob_cap
        # OrderedDict: flow -> last_path  (LRU order: first=oldest)
        self._probation = OrderedDict()
        self._protected = OrderedDict()

    def lookup_and_update(self, flow, path, ts=0):
        # --- In protected segment: refresh LRU position ---
        if flow in self._protected:
            old = self._protected[flow]
            self._protected.move_to_end(flow)
            self._protected[flow] = path
            return (old == path), False

        # --- In probation: promote to protected ---
        if flow in self._probation:
            old = self._probation.pop(flow)   # free one slot in probation
            hit = (old == path)
            if self._prot_cap == 0:
                # Degenerate case: capacity=1 => no protected segment.
                self._probation[flow] = path
                return hit, False
            if len(self._protected) >= self._prot_cap:
                # Demote LRU of protected back to probation.
                # Probation has one free slot (just popped), so no eviction.
                dem_flow, dem_path = self._protected.popitem(last=False)
                self._probation[dem_flow] = dem_path
            self._protected[flow] = path
            return hit, False    # promotion never evicts (total stays the same)

        # --- New flow: insert into probation ---
        evicted = False
        if len(self._probation) >= self._prob_cap:
            self._probation.popitem(last=False)   # evict LRU of probation only
            evicted = True
        self._probation[flow] = path
        return False, evicted


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

def simulate(records, cache, oracle=None, use_fast=False, capacity_samples=None, capacity_sample_every=1000) -> CacheResult:
    """
    Replay records through cache.  If oracle supplied, classify each miss as
    necessary or redundant.  If oracle is None, every miss counts as necessary
    (use this only for unbounded caches that are their own oracle).
    """
    result = CacheResult(cache_name=cache.name, capacity=cache.capacity)

    track_capacity = capacity_samples is not None and cache.capacity != float('inf')
    if track_capacity:
        use_fast = False

    if use_fast and _simulate_records_fast is not None:
        (
            total,
            hits,
            necessary_forwards,
            new_route_forwards,
            route_change_forwards,
            redundant_forwards,
            evictions,
        ) = _simulate_records_fast(records, cache)
        result.total = total
        result.hits = hits
        result.necessary_forwards = necessary_forwards
        result.new_route_forwards = new_route_forwards
        result.route_change_forwards = route_change_forwards
        result.redundant_forwards = redundant_forwards
        result.evictions = evictions
        return result
    # Collector-side oracle view: flow -> set of previously forwarded paths.
    collector_seen_paths = {}

    sample_every = max(1, int(capacity_sample_every))
    last_ts = 0

    for r in records:
        flow = r['flow']
        path = tuple(r['sw'])
        ts   = r['ts'][-1] if r['ts'] else 0
        last_ts = ts
        result.total += 1


        hit, evicted = cache.lookup_and_update(flow, path, ts)
        if evicted:
            result.evictions += 1

        if hit:
            result.hits += 1
        else:
            # Classify miss against infinite-memory collector state.
            seen_paths = collector_seen_paths.get(flow)
            if seen_paths is None:
                result.necessary_forwards += 1
                result.new_route_forwards += 1
                collector_seen_paths[flow] = {path}
            elif path not in seen_paths:
                result.necessary_forwards += 1
                result.route_change_forwards += 1
                seen_paths.add(path)
            else:
                # Collector already has this exact route; this forward is redundant.
                result.redundant_forwards += 1

        if track_capacity and (result.total == 1 or result.total % sample_every == 0):
            slots = cache_slots_used(cache)
            if slots is not None:
                capacity_samples.append((result.total, ts, slots))

    if track_capacity and result.total > 0:
        slots = cache_slots_used(cache)
        if slots is not None and (
            not capacity_samples or capacity_samples[-1][0] != result.total
        ):
            capacity_samples.append((result.total, last_ts, slots))  # pragma: no cover

    return result


def run_oracle_and_cache(
    records_list,
    cache_factory,
    oracle_factory=None,
    use_fast=False,
    capacity_curves=None,
    capacity_sample_every=1000,
):
    """
    Run oracle and a bounded cache over the same record list.
    oracle_factory defaults to Infinite.
    Returns CacheResult.
    """
    if oracle_factory is None:
        oracle_factory = InfiniteLastPath
    oracle = oracle_factory()
    cache = cache_factory()
    samples = [] if capacity_curves is not None else None
    result = simulate(
        records_list,
        cache,
        oracle,
        use_fast=use_fast,
        capacity_samples=samples,
        capacity_sample_every=capacity_sample_every,
    )
    if capacity_curves is not None and samples:
        capacity_curves[(result.cache_name, int(result.capacity))] = samples
    return result


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------

SWEEP_SIZES = [4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096]


def sweep(records, use_fast=False, capacity_curves=None, capacity_sample_every=1000):
    """Run all cache policies across SWEEP_SIZES, return list of CacheResult."""
    results = []

    # Unbounded baseline (no oracle needed, it is the oracle)
    results.append(simulate(records, InfiniteLastPath(), oracle=None))

    # TTL values to sweep — expressed in picoseconds.
    # With path_burst=64 at 10Gbps, paths change every ~460µs.
    TTL_SWEEP = {
        "0.1ms":    100_000_000,
        "0.5ms":    500_000_000,
        "2ms":    2_000_000_000,
        "10ms":  10_000_000_000,
    }

    for size in SWEEP_SIZES:
        for factory in [
            lambda s=size: LRULastPath(s),
            lambda s=size: FIFOLastPath(s),
            lambda s=size: LFULastPath(s),
            lambda s=size: TinyLFULRU(s),
            lambda s=size: TinyCacheLRU(s),
            lambda s=size: AdmissionFilterLRU(s),
            lambda s=size: PendingAdmissionLRU(s),
            lambda s=size: PITCollapsedLRU(s),
            lambda s=size: AdaptiveAdmissionLRU(s),
            lambda s=size: OnlineAdaptiveAdmissionLRU(s),
            lambda s=size: TimingBloomLRU(s),
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

        for label, ttl_ps in TTL_SWEEP.items():
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


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_results(results):
    print(f"\n{'Cache':<22} {'Cap':>6}  {'Total':>7}  "
          f"{'Suppressed':>10}  {'Supp%':>6}  "
          f"{'Forwarded':>10}  {'Fwd%':>6}  "
          f"{'New':>8}  {'Change':>8}  "
          f"{'Redundant':>10}  {'Redund%':>8}  "
          f"{'Evictions':>9}")
    print('-' * 120)
    for r in results:
        cap = f"{r.capacity}" if r.capacity != float('inf') else "inf"
        print(f"  {r.cache_name:<20} {cap:>6}  {r.total:>7,}  "
              f"{r.hits:>10,}  {100*r.suppression_rate:>5.1f}%  "
              f"{r.forwards:>10,}  {100*r.forward_rate:>5.1f}%  "
              f"{r.new_route_forwards:>8,}  {r.route_change_forwards:>8,}  "
              f"{r.redundant_forwards:>10,}  {100*r.redundancy_rate:>7.1f}%  "
              f"{r.evictions:>9,}")


def write_csv(results, path):
    with open(path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['cache', 'capacity', 'total', 'hits', 'suppression_rate',
                    'forwards', 'forward_rate', 'necessary_forwards',
                    'new_route_forwards', 'route_change_forwards',
                    'redundant_forwards', 'redundancy_rate', 'evictions'])
        for r in results:
            cap = r.capacity if r.capacity != float('inf') else -1
            w.writerow([r.cache_name, cap, r.total, r.hits,
                        round(r.suppression_rate, 4),
                        r.forwards, round(r.forward_rate, 4),
                        r.necessary_forwards, r.new_route_forwards,
                        r.route_change_forwards, r.redundant_forwards,
                        round(r.redundancy_rate, 4), r.evictions])
    print(f"\nCSV written to {path}")


def write_capacity_csv(capacity_curves, path):
    with open(path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow([
            'cache',
            'capacity',
            'record_index',
            'timestamp_ps',
            'slots_used',
            'fill_ratio',
            'fill_percent',
        ])
        for (cache_name, capacity) in sorted(capacity_curves.keys(), key=lambda k: (k[0], k[1])):
            if capacity <= 0 or math.isinf(capacity):
                continue
            for rec_idx, ts_ps, slots_used in capacity_curves[(cache_name, capacity)]:
                fill_ratio = min(1.0, max(0.0, slots_used / capacity))
                w.writerow([
                    cache_name,
                    capacity,
                    rec_idx,
                    ts_ps,
                    slots_used,
                    round(fill_ratio, 6),
                    round(fill_ratio * 100.0, 4),
                ])
    print(f"\nCapacity CSV written to {path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('logfile', nargs='?', default='dash_logs/log2.txt')
    ap.add_argument('--sweep', action='store_true',
                    help='Sweep all cache sizes and policies')
    ap.add_argument('--cache', choices=['lru', 'lfu', 'admission', 'pending_admission', 'pit', 'adaptive',
                                          'online_adaptive',
                                          'bloom',
                                          'fifo', 'tiny_lfu', 'tiny_cache', 'lru_ttl', 'f_inv', 'cache_int', 'life_ttl', 'infinite_lp'],
                    default='lru', help='Cache policy for single run')
    ap.add_argument('--size', type=int, default=64,
                    help='Cache capacity (number of flow slots) for single run')
    ap.add_argument('--pending-reset-every', type=int, default=0,
                    help='Periodically clear pending sketch every N records (0 disables)')
    ap.add_argument('--bloom-bits', type=int, default=1 << 18,
                    help='Bloom filter size in bits per filter (default: 262144)')
    ap.add_argument('--bloom-hashes', type=int, default=4,
                    help='Number of Bloom hash functions (default: 4)')
    ap.add_argument('--bloom-epoch-records', type=int, default=256,
                    help='Rotate Bloom windows every N INT records (short epochs are stricter)')
    ap.add_argument('--ttl-ms', type=float, default=10.0,
                    help='Keep-alive TTL in milliseconds for LRUTTL (default 10ms)')
    ap.add_argument('--fresh-ttl-ms', type=float, default=2.0,
                    help='Freshness TTL in milliseconds for FreshnessInvalidationLRU (default 2ms)')
    ap.add_argument('--dual-dyn-ttl-ms', type=float, default=0.5,
                    help='Dynamic-class TTL in milliseconds for DualFreshnessLRU (default 0.5ms)')
    ap.add_argument('--dual-stable-hits', type=int, default=3,
                    help='Stable hits needed to promote flow to static class in CacheINTFreshnessLRU')
    ap.add_argument('--pit-download-us', type=float, default=2.0,
                    help='PIT download delay in microseconds for PITCollapsedLRU (default 2us)')
    ap.add_argument('--fast', action='store_true',
                    help='Use optional Cython fast-path if available')
    ap.add_argument('--life-min-ttl-ms', type=float, default=0.1,
                    help='Minimum per-flow TTL in milliseconds for FlowLifetimeAdaptiveTTL (default 0.1ms)')
    ap.add_argument('--life-max-ttl-ms', type=float, default=20.0,
                    help='Maximum per-flow TTL in milliseconds for FlowLifetimeAdaptiveTTL (default 20ms)')
    ap.add_argument('--life-ema-alpha', type=float, default=0.2,
                    help='EMA alpha for per-flow gap learning in FlowLifetimeAdaptiveTTL (default 0.2)')
    ap.add_argument('--life-ttl-multiplier', type=float, default=4.0,
                    help='Multiplier mapping learned inter-arrival gap to TTL in FlowLifetimeAdaptiveTTL (default 4.0)')
    ap.add_argument('--csv', metavar='FILE',
                    help='Write sweep results to CSV file')
    ap.add_argument('--capacity-csv', metavar='FILE',
                    help='Write cache pressure samples (occupancy over time) to CSV file')
    ap.add_argument('--capacity-sample-every', type=int, default=1000,
                    help='Record one capacity sample every N packets (default: 1000)')
    ap.add_argument('--quiet-table', action='store_true',
                    help='Suppress printing the final sweep table to stdout')
    args = ap.parse_args()

    print(f"Parsing {args.logfile} ...", file=sys.stderr)
    records = list(parse(args.logfile))
    print(f"Loaded {len(records):,} INT records", file=sys.stderr)

    if not records:
        print("WARN: No INT records parsed from input log — skipping (empty dataset).", file=sys.stderr)
        sys.exit(0)

    if args.sweep:
        capacity_curves = {} if args.capacity_csv else None
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
        if args.capacity_csv and capacity_curves is not None:
            write_capacity_csv(capacity_curves, args.capacity_csv)
    else:
        ttl_ps = int(args.ttl_ms * 1_000_000_000)
        fresh_ttl_ps = int(args.fresh_ttl_ms * 1_000_000_000)
        dual_dyn_ttl_ps = int(args.dual_dyn_ttl_ms * 1_000_000_000)
        pit_download_ps = int(args.pit_download_us * 1_000_000)
        life_min_ttl_ps = int(args.life_min_ttl_ms * 1_000_000_000)
        life_max_ttl_ps = int(args.life_max_ttl_ms * 1_000_000_000)
        cache_map = {
            'lru':          lambda: LRULastPath(args.size),
            'lfu':          lambda: LFULastPath(args.size),
            'admission':    lambda: AdmissionFilterLRU(
                args.size,
                pending_reset_every=args.bloom_epoch_records,
                bloom_bits=args.bloom_bits,
                bloom_hashes=args.bloom_hashes,
            ),
            'pending_admission': lambda: PendingAdmissionLRU(args.size, pending_reset_every=args.pending_reset_every),
            'pit':          lambda: PITCollapsedLRU(args.size, download_delay_ps=pit_download_ps),
            'adaptive':     lambda: AdaptiveAdmissionLRU(args.size, pending_reset_every=args.pending_reset_every),
            'online_adaptive': lambda: OnlineAdaptiveAdmissionLRU(args.size),
            'bloom':        lambda: TimingBloomLRU(args.size, args.bloom_bits, args.bloom_hashes, args.bloom_epoch_records),
            'fifo':         lambda: FIFOLastPath(args.size),
            'tiny_lfu':     lambda: TinyLFULRU(args.size),
            'tiny_cache':   lambda: TinyCacheLRU(args.size),
            'lru_ttl':      lambda: LRULastPathTTL(args.size, ttl_ps),
            'f_inv':        lambda: FreshnessInvalidationLRU(args.size, fresh_ttl_ps),
            'cache_int':    lambda: CacheINTFreshnessLRU(args.size, dual_dyn_ttl_ps, args.dual_stable_hits),
            'life_ttl':     lambda: FlowLifetimeAdaptiveTTL(
                args.size,
                min_ttl_ps=life_min_ttl_ps,
                max_ttl_ps=life_max_ttl_ps,
                ema_alpha=args.life_ema_alpha,
                ttl_multiplier=args.life_ttl_multiplier,
            ),
            'infinite_lp':  lambda: InfiniteLastPath(),
        }
        unbounded = args.cache == 'infinite_lp'
        cache = cache_map[args.cache]()
        oracle = None if unbounded else InfiniteLastPath()
        cap_samples = [] if args.capacity_csv else None
        result = simulate(
            records,
            cache,
            oracle,
            use_fast=args.fast,
            capacity_samples=cap_samples,
            capacity_sample_every=args.capacity_sample_every,
        )
        print(result)
        if args.capacity_csv and cap_samples and result.capacity != float('inf'):
            write_capacity_csv({(result.cache_name, int(result.capacity)): cap_samples}, args.capacity_csv)
