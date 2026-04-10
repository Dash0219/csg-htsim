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
  InfiniteLastPath      — unbounded dict: flow → last_path       (oracle / baseline A)
  LRULastPath(N)        — N slots, LRU eviction, stores last path per flow
  FIFOLastPath(N)       — N slots, FIFO eviction
  LFULastPath(N)        — N slots, LFU eviction (least-frequently-seen flow evicted)
                          classic frequency vs recency comparison against LRU
  VolatilityAwareLRU(N) — N slots, evicts most path-stable flow first
                          domain-motivated: volatile flows change path often so keeping
                          them in cache is more valuable than keeping stable flows
  AdmissionFilterLRU(N)     — N slots, LRU eviction, but only admits a flow after its
                              second encounter (second-chance admission).  Filters
                              short-lived flows that would otherwise pollute the cache.
  SegmentedLRU(N)           — N slots split into probation (N//4) + protected (N*3//4).
                              New flows enter probation; a second access promotes to protected.
                              Protected entries can only be evicted by demotion, not new arrivals.
                              Same total budget as LRU — no separate sketch needed.
    AdaptiveAdmissionLRU(N) — AdmissionFilterLRU with pressure-adaptive bypass.
                                                        Under low eviction pressure, behaves like plain LRU
                                                        (admits immediately). Under high pressure, switches
                                                        to second-chance admission to reduce pollution.
    TimingBloomLRU(N)       — Pressure-adaptive 2-window timing Bloom admission.
                                                        Bloom gating is only enforced while the cache is
                                                        under sustained eviction pressure.
    TwoFilterOHWLRU(N)      — Pressure-adaptive Akamai-style OHW with two Bloom
                                                        filters. Under pressure, a flow is admitted on
                                                        second touch (f1/f2 evidence); otherwise bypassed.
    FreshnessInvalidationLRU(N)
                                                    — N slots, LRU + hard freshness expiration.
                                                        Expired entries are invalidated before decision,
                                                        approximating collector-driven stale-state purge.
    DualFreshnessLRU(N)     — N slots, LRU + dual TTL classes.
                                                        Flows that stay stable for K hits are treated as
                                                        static (long TTL), otherwise time-variant (short TTL).

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
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import cast


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


# ---------------------------------------------------------------------------
# Cache implementations
# ---------------------------------------------------------------------------

class InfiniteLastPath:
    """Oracle / baseline A — never evicts and remembers all seen paths per flow."""
    name = "InfiniteLastPath"
    capacity = float('inf')

    def __init__(self):
        self._store = {}  # flow_id -> set(path tuples)

    def lookup_and_update(self, flow, path, ts=0):
        """
        Returns (hit: bool, eviction: bool).
        hit=True  → suppress (path already seen for this flow)
        hit=False → forward (first observation of this flow/path pair)
        """
        seen = self._store.get(flow)
        if seen is None:
            self._store[flow] = {path}
            return False, False
        if path in seen:
            return True, False
        seen.add(path)
        return False, False


class LRULastPath:
    """
    Bounded LRU cache.  N slots, one per flow, stores last_path.
    Eviction of a flow means its path is forgotten; the next packet for
    that flow will be a miss (possibly redundant).
    """
    name = "LRULastPath"

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
    name = "FIFOLastPath"

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
    name = "LRULastPathTTL"

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
    name = "LFULastPath"

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
    LRU cache with second-chance admission control.

    A flow is only admitted to the main cache after it has been seen a second
    time (second-chance / TinyLFU-style admission filter).

    On the first encounter the packet is always forwarded (miss), but the flow
    is placed in a bounded pending sketch rather than the main cache.
    On the second+ encounter the flow is admitted and handled by the main LRU.

    The pending sketch has the same capacity as the main cache (total memory
    budget = 2 × capacity), and evicts FIFO when full.  In this simulator the
    sketch is an exact table; a hardware implementation would typically use a
    compact probabilistic structure (e.g., a counting Bloom filter).

    When a flow is evicted from the main cache it loses its cached state and
    must re-enter via the pending sketch on its next encounter (second-chance
    restarts on eviction — conservative but simple).

    Key tradeoff vs plain LRU:
      + Protects main cache slots from one-shot / short-lived flows
      + At small capacities, pending absorbs first-encounter misses cheaply
      - Two encounters needed to start suppressing a new flow
      - One extra necessary forward per new long-lived flow (the first encounter)
    """
    name = "AdmissionFilterLRU"

    def __init__(self, capacity, pending_size=None, pending_reset_every=0):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        self.capacity    = capacity
        # Pending sketch is the same size as the main cache by default.
        # This represents a realistic total memory budget of 2 × capacity.
        self._pending_cap = pending_size if pending_size is not None else capacity
        if self._pending_cap <= 0:
            raise ValueError("pending_size must be > 0")
        # Optional periodic reset of pending sketch to emulate Bloom aging.
        # Default 0 disables reset (current FIFO sketch already self-refreshes).
        self._pending_reset_every = pending_reset_every
        self._ops = 0
        self._store   = OrderedDict()  # admitted flows: flow_id -> last_path  (LRU)
        self._pending = OrderedDict()  # pending flows: flow_id -> first_path   (FIFO)

    def lookup_and_update(self, flow, path, ts=0):
        evicted = False
        self._ops += 1
        if self._pending_reset_every and self._ops % self._pending_reset_every == 0:
            self._pending.clear()

        # --- Already admitted to main cache ---
        if flow in self._store:
            old = self._store[flow]
            self._store.move_to_end(flow)
            self._store[flow] = path
            return (old == path), False

        # --- In pending sketch (seen exactly once before) ---
        if flow in self._pending:
            old = self._pending.pop(flow)           # remove from sketch
            # Admit to main cache
            if len(self._store) >= self.capacity:
                self._store.popitem(last=False)     # evict LRU from main cache
                evicted = True
            self._store[flow] = path
            # Hit only if path is unchanged since first encounter
            return (old == path), evicted

        # --- First encounter: place in pending sketch ---
        if len(self._pending) >= self._pending_cap:
            self._pending.popitem(last=False)       # FIFO evict oldest pending entry
        self._pending[flow] = path
        return False, evicted   # always forward on first sight


class AdaptiveAdmissionLRU:
    """
    AdmissionFilterLRU with pressure-adaptive bypass.

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


class TimingBloomLRU:
    """
    LRU cache with timing Bloom admission.

    A new flow is admitted only if its ID appears in the recent 2-window Bloom
    history. Otherwise it is bypassed and recorded in the current Bloom window.
    """
    name = "TimingBloomLRU"

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

def simulate(records, cache, oracle=None) -> CacheResult:
    """
    Replay records through cache.  If oracle supplied, classify each miss as
    necessary or redundant.  If oracle is None, every miss counts as necessary
    (use this only for unbounded caches that are their own oracle).
    """
    result = CacheResult(cache_name=cache.name, capacity=cache.capacity)
    # Collector-side oracle view: flow -> set of previously forwarded paths.
    collector_seen_paths = {}

    for r in records:
        flow = r['flow']
        path = tuple(r['sw'])
        ts   = r['ts'][-1] if r['ts'] else 0
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

    return result


def run_oracle_and_cache(records_list, cache_factory, oracle_factory=None):
    """
    Run oracle and a bounded cache over the same record list.
    oracle_factory defaults to InfiniteLastPath.
    Returns CacheResult.
    """
    if oracle_factory is None:
        oracle_factory = InfiniteLastPath
    oracle = oracle_factory()
    cache  = cache_factory()
    return simulate(records_list, cache, oracle)


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------

SWEEP_SIZES = [4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096]


def sweep(records):
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
        # --- Recency vs frequency vs domain-aware eviction ---
        for factory in [
            lambda s=size: LRULastPath(s),
            lambda s=size: LFULastPath(s),
            lambda s=size: VolatilityAwareLRU(s),
            lambda s=size: AdmissionFilterLRU(s),
            lambda s=size: AdaptiveAdmissionLRU(s),
            lambda s=size: OnlineAdaptiveAdmissionLRU(s),
            lambda s=size: SegmentedLRU(s),
            lambda s=size: TimingBloomLRU(s),
            lambda s=size: TwoFilterOHWLRU(s),
            lambda s=size: FreshnessInvalidationLRU(s),
            lambda s=size: DualFreshnessLRU(s),
            lambda s=size: OnlineAdaptiveDualTTL(s),
        ]:
            r = run_oracle_and_cache(records, factory)
            results.append(r)

        # --- TTL sweep ---
        for label, ttl_ps in TTL_SWEEP.items():
            r = run_oracle_and_cache(records, lambda s=size, t=ttl_ps: LRULastPathTTL(s, t))
            r.cache_name = f"LRUTtl({label})"
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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('logfile', nargs='?', default='dash_logs/log2.txt')
    ap.add_argument('--sweep', action='store_true',
                    help='Sweep all cache sizes and policies')
    ap.add_argument('--cache', choices=['lru', 'lfu', 'volatility', 'admission', 'adaptive',
                                          'online_adaptive',
                                          'slru', 'bloom', 'ohw2',
                                          'fifo', 'lru_ttl', 'f_inv', 'dual_fresh', 'online_dual_ttl', 'infinite_lp'],
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
                    help='Keep-alive TTL in milliseconds for LRULastPathTTL (default 10ms)')
    ap.add_argument('--fresh-ttl-ms', type=float, default=2.0,
                    help='Freshness TTL in milliseconds for FreshnessInvalidationLRU (default 2ms)')
    ap.add_argument('--dual-dyn-ttl-ms', type=float, default=0.5,
                    help='Dynamic-class TTL in milliseconds for DualFreshnessLRU (default 0.5ms)')
    ap.add_argument('--dual-static-ttl-ms', type=float, default=10.0,
                    help='Static-class TTL in milliseconds for DualFreshnessLRU (default 10ms)')
    ap.add_argument('--dual-stable-hits', type=int, default=3,
                    help='Stable hits needed to promote flow to static class in DualFreshnessLRU')
    ap.add_argument('--csv', metavar='FILE',
                    help='Write sweep results to CSV file')
    args = ap.parse_args()

    print(f"Parsing {args.logfile} ...", file=sys.stderr)
    records = list(parse(args.logfile))
    print(f"Loaded {len(records):,} INT records", file=sys.stderr)

    if args.sweep:
        results = sweep(records)
        print_results(results)
        if args.csv:
            write_csv(results, args.csv)
    else:
        ttl_ps = int(args.ttl_ms * 1_000_000_000)
        fresh_ttl_ps = int(args.fresh_ttl_ms * 1_000_000_000)
        dual_dyn_ttl_ps = int(args.dual_dyn_ttl_ms * 1_000_000_000)
        dual_static_ttl_ps = int(args.dual_static_ttl_ms * 1_000_000_000)
        cache_map = {
            'lru':          lambda: LRULastPath(args.size),
            'lfu':          lambda: LFULastPath(args.size),
            'volatility':   lambda: VolatilityAwareLRU(args.size),
            'admission':    lambda: AdmissionFilterLRU(args.size, pending_reset_every=args.pending_reset_every),
            'adaptive':     lambda: AdaptiveAdmissionLRU(args.size, pending_reset_every=args.pending_reset_every),
            'online_adaptive': lambda: OnlineAdaptiveAdmissionLRU(args.size),
            'slru':         lambda: SegmentedLRU(args.size),
            'bloom':        lambda: TimingBloomLRU(args.size, args.bloom_bits, args.bloom_hashes, args.bloom_epoch_records),
            'ohw2':         lambda: TwoFilterOHWLRU(args.size, args.bloom_bits, args.bloom_hashes, args.bloom_epoch_records),
            'fifo':         lambda: FIFOLastPath(args.size),
            'lru_ttl':      lambda: LRULastPathTTL(args.size, ttl_ps),
            'f_inv':        lambda: FreshnessInvalidationLRU(args.size, fresh_ttl_ps),
            'dual_fresh':   lambda: DualFreshnessLRU(args.size, dual_dyn_ttl_ps, dual_static_ttl_ps, args.dual_stable_hits),
            'online_dual_ttl': lambda: OnlineAdaptiveDualTTL(args.size, dual_dyn_ttl_ps, dual_static_ttl_ps, stable_hit_threshold=args.dual_stable_hits),
            'infinite_lp':  lambda: InfiniteLastPath(),
        }
        unbounded = args.cache == 'infinite_lp'
        cache = cache_map[args.cache]()
        oracle = None if unbounded else InfiniteLastPath()
        result = simulate(records, cache, oracle)
        print(result)
