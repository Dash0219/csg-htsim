"""
Congestion cache simulator using range-based detection (INTCollector / cache-INT approach).

Cache key    : (switch_id, switch_type) encoded as "sw_id:sw_type"  (switch-level default)
               or flow_id string (flow-level with --key-level flow)
Cached value : last forwarded queue size for that key

Detection    : Forward a report when the switch is not yet cached, OR
               |new_qs - cached_qs| > range_threshold.
               Because cached_qs depends on which entries are in cache, event detection is
               inseparable from the cache simulation — it cannot be pre-computed.

Workflow:
  1. Parse ALL INT hop records from the trace (no pre-filtering by absolute threshold).
  2. Simulate all cache policies over a range of cache sizes.
  3. For each hop, a miss occurs when the switch is not in cache or the queue size has
     changed beyond the threshold; a hit means the cached value is still close enough
     and the report is suppressed.

Implemented caches
------------------
    InfiniteQS             — unbounded dict: key → last_qs          (oracle / baseline)
    LRU(N)                 — N slots, LRU eviction, stores last_qs per key
    FIFO(N)                — N slots, FIFO eviction
    LFU(N)                 — N slots, LFU eviction (least-frequently-updated key evicted)
    OneHitWonderLRU(N)     — N slots, LRU eviction, Bloom admission filter
    PendingAdmissionLRU(N) — N slots, LRU eviction + exact pending table
    PITCollapsedLRU(N)     — N slots, PIT-style inflight collapsing
    AdaptiveAdmissionLRU(N)— OneHitWonder with pressure-adaptive bypass
    OnlineAdaptiveAdmissionLRU(N)
    TimeLimitedBloomLRU(N) — Bloom gating under eviction pressure
    TinyLFULRU(N)          — LRU eviction + TinyLFU admission sketch
    TinyCacheLRU(N)        — LRU eviction + TinyCache admission filter
    FreshnessInvalidationLRU(N) — LRU + hard freshness expiration
    CacheINTFreshnessLRU(N)— Cache-INT-inspired split handling
    FlowLifetimeAdaptiveTTL(N)  — per-key adaptive freshness window
    LRUTTL(N)              — LRU with time-to-live per entry (freshness keep-alive)

Usage
-----
  # single run
  python cache_sim_congestion_int.py log.txt --cache lru --size 64

  # sweep cache sizes and compare policies
  python cache_sim_congestion_int.py log.txt --sweep
  python cache_sim_congestion_int.py log.txt --sweep --csv results.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import math
import random
import sys
from collections import OrderedDict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from fyp.dash_scripts.cache_sim import parse
except ModuleNotFoundError:
    from cache_sim import parse  # type: ignore


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class CongestResult:
    cache_name: str
    capacity: int           # float('inf') for unbounded
    total: int = 0
    hits: int = 0               # suppressed: |new_qs - cached_qs| <= threshold
    necessary_forwards: int = 0 # oracle also misses: new key OR value changed beyond threshold
    new_route_forwards: int = 0 # key never seen by oracle before
    route_change_forwards: int = 0  # key known to oracle but value changed beyond threshold
    redundant_forwards: int = 0 # oracle would suppress, but bounded cache evicted and lost track
    evictions: int = 0

    @property
    def forwards(self) -> int:
        return self.necessary_forwards + self.redundant_forwards

    @property
    def suppression_rate(self) -> float:
        return self.hits / self.total if self.total else 0.0

    @property
    def forward_rate(self) -> float:
        return self.forwards / self.total if self.total else 0.0

    @property
    def redundancy_rate(self) -> float:
        return self.redundant_forwards / self.forwards if self.forwards else 0.0

    @property
    def efficiency(self) -> float:
        return self.necessary_forwards / self.forwards if self.forwards else 1.0

    def __str__(self) -> str:
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
    if hasattr(cache, '_store') and isinstance(cache._store, (dict, OrderedDict)):
        return len(cache._store)
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
# Shared Bloom filter utility
# ---------------------------------------------------------------------------

class RollingBloomFilter:
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


# ---------------------------------------------------------------------------
# Cache implementations
# Each cache stores last_qs (int) per key and detects changes via range_threshold.
# Interface: process(key, new_qs, ts) -> (hit: bool, evicted: bool)
#   hit=True  → suppress (|new_qs - cached_qs| <= threshold, and entry is fresh)
#   hit=False → forward (new entry, threshold exceeded, or freshness expired)
# ---------------------------------------------------------------------------

class InfiniteQS:
    """Oracle / baseline — unbounded, never evicts, stores exact last_qs per key."""
    name = "Infinite"
    capacity = float('inf')

    def __init__(self, range_threshold: int = 0):
        self.range_threshold = range_threshold
        self._store: Dict[str, int] = {}
        self._first_seen: set = set()  # keys ever inserted (for new vs change classification)

    def process(self, key: str, new_qs: int, ts: int = 0) -> Tuple[bool, bool]:
        if key in self._store:
            if abs(new_qs - self._store[key]) <= self.range_threshold:
                return True, False
            self._store[key] = new_qs
            return False, False
        self._store[key] = new_qs
        self._first_seen.add(key)
        return False, False


class LRUQSCache:
    name = "LRU"

    def __init__(self, capacity: int, range_threshold: int = 0):
        self.capacity = capacity
        self.range_threshold = range_threshold
        self._store: OrderedDict[str, int] = OrderedDict()

    def process(self, key: str, new_qs: int, ts: int = 0) -> Tuple[bool, bool]:
        if key in self._store:
            cached = self._store[key]
            self._store.move_to_end(key)
            if abs(new_qs - cached) <= self.range_threshold:
                return True, False
            self._store[key] = new_qs
            return False, False
        evicted = False
        if len(self._store) >= self.capacity:
            self._store.popitem(last=False)
            evicted = True
        self._store[key] = new_qs
        return False, evicted


class FIFOQSCache:
    name = "FIFO"

    def __init__(self, capacity: int, range_threshold: int = 0):
        self.capacity = capacity
        self.range_threshold = range_threshold
        self._store: Dict[str, int] = {}
        self._order: deque = deque()

    def process(self, key: str, new_qs: int, ts: int = 0) -> Tuple[bool, bool]:
        if key in self._store:
            cached = self._store[key]
            if abs(new_qs - cached) <= self.range_threshold:
                return True, False
            self._store[key] = new_qs
            return False, False
        evicted = False
        if len(self._store) >= self.capacity:
            victim = self._order.popleft()
            del self._store[victim]
            evicted = True
        self._store[key] = new_qs
        self._order.append(key)
        return False, evicted


class LFUQSCache:
    """Evict the key that has been forwarded (missed) least often."""
    name = "LFU"

    def __init__(self, capacity: int, range_threshold: int = 0):
        self.capacity = capacity
        self.range_threshold = range_threshold
        self._store: Dict[str, int] = {}
        self._freq: Dict[str, int] = {}
        self._seq_of: Dict[str, int] = {}
        self._heap: List = []
        self._seq = 0

    def _evict_one(self) -> None:
        while self._heap:
            freq, seq, key = heapq.heappop(self._heap)
            if key in self._store and self._freq[key] == freq and self._seq_of[key] == seq:
                del self._store[key]
                del self._freq[key]
                del self._seq_of[key]
                return

    def process(self, key: str, new_qs: int, ts: int = 0) -> Tuple[bool, bool]:
        if key in self._store:
            cached = self._store[key]
            self._freq[key] += 1
            self._seq += 1
            self._seq_of[key] = self._seq
            heapq.heappush(self._heap, (self._freq[key], self._seq, key))
            if abs(new_qs - cached) <= self.range_threshold:
                return True, False
            self._store[key] = new_qs
            return False, False
        evicted = False
        if len(self._store) >= self.capacity:
            self._evict_one()
            evicted = True
        self._seq += 1
        self._store[key] = new_qs
        self._freq[key] = 1
        self._seq_of[key] = self._seq
        heapq.heappush(self._heap, (1, self._seq, key))
        return False, evicted


class LRUQSCacheTTL:
    """LRU with time-to-live per entry. Expired entries are always forwarded."""
    name = "LRUTTL"

    def __init__(self, capacity: int, range_threshold: int = 0, ttl_ps: int = 10_000_000_000):
        self.capacity = capacity
        self.range_threshold = range_threshold
        self.ttl_ps = ttl_ps
        self._store: OrderedDict[str, Tuple[int, int]] = OrderedDict()  # key -> (qs, last_ts)

    def process(self, key: str, new_qs: int, ts: int = 0) -> Tuple[bool, bool]:
        if key in self._store:
            cached_qs, last_ts = self._store[key]
            self._store.move_to_end(key)
            if abs(new_qs - cached_qs) <= self.range_threshold and (ts - last_ts) < self.ttl_ps:
                return True, False
            self._store[key] = (new_qs, ts)
            return False, False
        evicted = False
        if len(self._store) >= self.capacity:
            self._store.popitem(last=False)
            evicted = True
        self._store[key] = (new_qs, ts)
        return False, evicted


class FreshnessInvalidationQS:
    """LRU + hard freshness invalidation. Stale entries are evicted before decision."""
    name = "FreshnessInvalidationLRU"

    def __init__(self, capacity: int, range_threshold: int = 0, freshness_ttl_ps: int = 2_000_000_000):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        self.capacity = capacity
        self.range_threshold = range_threshold
        self.freshness_ttl_ps = freshness_ttl_ps
        self._store: OrderedDict[str, Tuple[int, int]] = OrderedDict()  # key -> (qs, ts)

    def process(self, key: str, new_qs: int, ts: int = 0) -> Tuple[bool, bool]:
        if key in self._store:
            cached_qs, cached_ts = self._store[key]
            if (ts - cached_ts) >= self.freshness_ttl_ps:
                del self._store[key]
            else:
                self._store.move_to_end(key)
                if abs(new_qs - cached_qs) <= self.range_threshold:
                    self._store[key] = (new_qs, ts)
                    return True, False
                self._store[key] = (new_qs, ts)
                return False, False
        evicted = False
        if len(self._store) >= self.capacity:
            self._store.popitem(last=False)
            evicted = True
        self._store[key] = (new_qs, ts)
        return False, evicted


class CacheINTFreshnessQS:
    """
    Cache-INT inspired freshness cache adapted for queue-size values.

    Classifies entries as dynamic (time-variant) or static (stable):
      - Dynamic entries use dynamic_ttl_ps; expire even if value is unchanged.
      - After stable_hit_threshold consecutive hits, entry becomes static (no TTL).
      - Any value change (|new - cached| > threshold) resets back to dynamic.
    """
    name = "CacheINTFreshnessLRU"

    def __init__(self, capacity: int, range_threshold: int = 0,
                 dynamic_ttl_ps: int = 500_000_000, stable_hit_threshold: int = 3):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        self.capacity = capacity
        self.range_threshold = range_threshold
        self.dynamic_ttl_ps = dynamic_ttl_ps
        self.stable_hit_threshold = stable_hit_threshold
        # key -> dict(qs, last_update_ts, stable_hits, is_static)
        self._store: OrderedDict = OrderedDict()

    def _evict_one(self) -> None:
        victim = None
        victim_ts = None
        for k, item in self._store.items():
            if item["is_static"]:
                continue
            if victim is None or item["last_update_ts"] < victim_ts:
                victim = k
                victim_ts = item["last_update_ts"]
        if victim is None:
            self._store.popitem(last=False)
            return
        del self._store[victim]

    def process(self, key: str, new_qs: int, ts: int = 0) -> Tuple[bool, bool]:
        if key in self._store:
            item = self._store[key]
            self._store.move_to_end(key)
            same_value = abs(new_qs - item["qs"]) <= self.range_threshold
            if same_value:
                item["stable_hits"] = min(item["stable_hits"] + 1, self.stable_hit_threshold)
                if item["stable_hits"] >= self.stable_hit_threshold:
                    item["is_static"] = True
                if item["is_static"] or (ts - item["last_update_ts"]) < self.dynamic_ttl_ps:
                    item["last_update_ts"] = ts
                    return True, False
                item["last_update_ts"] = ts
                return False, False
            item["qs"] = new_qs
            item["last_update_ts"] = ts
            item["stable_hits"] = 0
            item["is_static"] = False
            return False, False
        evicted = False
        if len(self._store) >= self.capacity:
            self._evict_one()
            evicted = True
        self._store[key] = {"qs": new_qs, "last_update_ts": ts, "stable_hits": 0, "is_static": False}
        return False, evicted


class FlowLifetimeAdaptiveTTLQS:
    """
    LRU with per-key adaptive freshness windows.

    Each key tracks an EMA of inter-arrival gap. TTL is derived from the EMA
    and clamped to configurable bounds:
      ttl(key) = clamp(ttl_multiplier * ema_gap, min_ttl_ps, max_ttl_ps)
    """
    name = "FlowLifetimeAdaptiveTTL"

    def __init__(self, capacity: int, range_threshold: int = 0,
                 min_ttl_ps: int = 100_000_000, max_ttl_ps: int = 20_000_000_000,
                 base_ttl_ps: int = 500_000_000, ema_alpha: float = 0.2,
                 ttl_multiplier: float = 4.0):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        self.capacity = capacity
        self.range_threshold = range_threshold
        self.min_ttl_ps = min_ttl_ps
        self.max_ttl_ps = max_ttl_ps
        self.base_ttl_ps = base_ttl_ps
        self.ema_alpha = ema_alpha
        self.ttl_multiplier = ttl_multiplier
        # key -> (qs, last_ts, ema_gap_ps, samples)
        self._store: OrderedDict = OrderedDict()

    def _effective_ttl(self, ema_gap_ps: int, samples: int) -> int:
        if samples <= 1:
            return self.base_ttl_ps
        ttl = int(ema_gap_ps * self.ttl_multiplier)
        return max(self.min_ttl_ps, min(self.max_ttl_ps, ttl))

    def _update_ema(self, prev_ema: int, gap_ps: int, samples: int) -> int:
        gap_ps = max(0, int(gap_ps))
        if samples <= 1:
            return gap_ps
        return int(self.ema_alpha * gap_ps + (1.0 - self.ema_alpha) * prev_ema)

    def process(self, key: str, new_qs: int, ts: int = 0) -> Tuple[bool, bool]:
        if key in self._store:
            cached_qs, last_ts, ema_gap_ps, samples = self._store[key]
            age = max(0, int(ts - last_ts))
            ttl_ps = self._effective_ttl(ema_gap_ps, samples)
            self._store.move_to_end(key)
            hit = abs(new_qs - cached_qs) <= self.range_threshold and age < ttl_ps
            samples += 1
            ema_gap_ps = self._update_ema(ema_gap_ps, age, samples)
            self._store[key] = (new_qs, ts, ema_gap_ps, samples)
            return hit, False
        evicted = False
        if len(self._store) >= self.capacity:
            self._store.popitem(last=False)
            evicted = True
        self._store[key] = (new_qs, ts, self.base_ttl_ps, 1)
        return False, evicted


class AdmissionFilterQS:
    """One-hit-wonder admission: admit to LRU cache only on second encounter within Bloom window."""
    name = "OneHitWonderLRU"

    def __init__(self, capacity: int, range_threshold: int = 0, pending_size=None,
                 pending_reset_every=0, bloom_bits=1 << 18, bloom_hashes=4):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        self.capacity = capacity
        self.range_threshold = range_threshold
        self._epoch = pending_reset_every
        self._ops = 0
        self._seen = RollingBloomFilter(bits=bloom_bits, hashes=bloom_hashes)
        self._store: OrderedDict[str, int] = OrderedDict()

    def _tick(self):
        self._ops += 1
        if self._epoch > 0 and self._ops % self._epoch == 0:
            self._seen.reset_epoch()

    def process(self, key: str, new_qs: int, ts: int = 0) -> Tuple[bool, bool]:
        self._tick()
        if key in self._store:
            cached = self._store[key]
            self._store.move_to_end(key)
            if abs(new_qs - cached) <= self.range_threshold:
                return True, False
            self._store[key] = new_qs
            return False, False
        seen_recently = self._seen.contains(key)
        self._seen.add(key)
        if not seen_recently:
            return False, False
        evicted = False
        if len(self._store) >= self.capacity:
            self._store.popitem(last=False)
            evicted = True
        self._store[key] = new_qs
        return False, evicted


class PendingAdmissionQS:
    """LRU with exact second-touch admission via a bounded FIFO pending table."""
    name = "PendingAdmissionLRU"

    def __init__(self, capacity: int, range_threshold: int = 0,
                 pending_size=None, pending_reset_every=0):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        self.capacity = capacity
        self.range_threshold = range_threshold
        self._pending_cap = pending_size if pending_size is not None else capacity
        self._pending_reset_every = pending_reset_every
        self._ops = 0
        self._store: OrderedDict[str, int] = OrderedDict()
        self._pending: OrderedDict[str, int] = OrderedDict()

    def process(self, key: str, new_qs: int, ts: int = 0) -> Tuple[bool, bool]:
        self._ops += 1
        if self._pending_reset_every and self._ops % self._pending_reset_every == 0:
            self._pending.clear()
        if key in self._store:
            cached = self._store[key]
            self._store.move_to_end(key)
            if abs(new_qs - cached) <= self.range_threshold:
                return True, False
            self._store[key] = new_qs
            return False, False
        if key in self._pending:
            self._pending.pop(key)
            evicted = False
            if len(self._store) >= self.capacity:
                self._store.popitem(last=False)
                evicted = True
            self._store[key] = new_qs
            return False, evicted
        if len(self._pending) >= self._pending_cap:
            self._pending.popitem(last=False)
        self._pending[key] = new_qs
        return False, False


class PITCollapsedQS:
    """LRU cache with PIT-style collapsed forwarding for inflight entries."""
    name = "PITCollapsedLRU"

    def __init__(self, capacity: int, range_threshold: int = 0,
                 download_delay_ps: int = 2_000_000, pit_capacity=None):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        self.capacity = capacity
        self.range_threshold = range_threshold
        self.download_delay_ps = download_delay_ps
        self.pit_capacity = pit_capacity if pit_capacity is not None else capacity
        self._store: OrderedDict[str, int] = OrderedDict()
        self._pit: OrderedDict[str, Tuple[int, int]] = OrderedDict()  # key -> (pending_qs, ready_ts)

    def _admit(self, key: str, qs: int) -> bool:
        evicted = False
        if len(self._store) >= self.capacity:
            self._store.popitem(last=False)
            evicted = True
        self._store[key] = qs
        return evicted

    def process(self, key: str, new_qs: int, ts: int = 0) -> Tuple[bool, bool]:
        evicted = False
        if key in self._pit:
            pending_qs, ready_ts = self._pit[key]
            if ts < ready_ts and abs(new_qs - pending_qs) <= self.range_threshold:
                self._pit.move_to_end(key)
                return True, False
            if ts >= ready_ts:
                evicted = self._admit(key, pending_qs)
                del self._pit[key]
            elif abs(new_qs - pending_qs) > self.range_threshold:
                self._pit[key] = (new_qs, ts + self.download_delay_ps)
                self._pit.move_to_end(key)
                return False, False
        if key in self._store:
            cached = self._store[key]
            self._store.move_to_end(key)
            if abs(new_qs - cached) <= self.range_threshold:
                return True, evicted
            self._store[key] = new_qs
            return False, evicted
        if len(self._pit) >= self.pit_capacity:
            self._pit.popitem(last=False)
        self._pit[key] = (new_qs, ts + self.download_delay_ps)
        return False, evicted


class AdaptiveAdmissionQS:
    """OneHitWonder with pressure-adaptive bypass: open admission under low pressure."""
    name = "AdaptiveAdmissionLRU"

    def __init__(self, capacity: int, range_threshold: int = 0, pending_size=None,
                 pending_reset_every=0, pressure_window=10000, eviction_high_watermark=0.02):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        self.capacity = capacity
        self.range_threshold = range_threshold
        self._pending_cap = pending_size if pending_size is not None else capacity
        self._pending_reset_every = pending_reset_every
        self._ops = 0
        self._pressure_window = pressure_window
        self._evict_high_watermark = eviction_high_watermark
        self._window_ops = 0
        self._window_evicts = 0
        self._under_pressure = False
        self._store: OrderedDict[str, int] = OrderedDict()
        self._pending: OrderedDict[str, int] = OrderedDict()

    def _update_pressure(self, evicted: bool):
        self._window_ops += 1
        if evicted:
            self._window_evicts += 1
        if self._window_ops >= self._pressure_window:
            ratio = self._window_evicts / self._window_ops
            self._under_pressure = ratio >= self._evict_high_watermark
            self._window_ops = 0
            self._window_evicts = 0

    def process(self, key: str, new_qs: int, ts: int = 0) -> Tuple[bool, bool]:
        self._ops += 1
        if self._pending_reset_every and self._ops % self._pending_reset_every == 0:
            self._pending.clear()
        if key in self._store:
            cached = self._store[key]
            self._store.move_to_end(key)
            hit = abs(new_qs - cached) <= self.range_threshold
            if not hit:
                self._store[key] = new_qs
            self._update_pressure(False)
            return hit, False
        if not self._under_pressure:
            evicted = False
            if len(self._store) >= self.capacity:
                self._store.popitem(last=False)
                evicted = True
            self._store[key] = new_qs
            self._update_pressure(evicted)
            return False, evicted
        if key in self._pending:
            self._pending.pop(key)
            evicted = False
            if len(self._store) >= self.capacity:
                self._store.popitem(last=False)
                evicted = True
            self._store[key] = new_qs
            self._update_pressure(evicted)
            return False, evicted
        if len(self._pending) >= self._pending_cap:
            self._pending.popitem(last=False)
        self._pending[key] = new_qs
        self._update_pressure(False)
        return False, False


class OnlineAdaptiveAdmissionQS:
    """Online adaptive admission: 3-mode strictness controller based on eviction and hit ratios."""
    name = "OnlineAdaptiveAdmissionLRU"

    def __init__(self, capacity: int, range_threshold: int = 0, pending_size=None,
                 pressure_window=10000, high_evict=0.03, low_evict=0.005,
                 weak_hit=0.70, strong_hit=0.92):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        self.capacity = capacity
        self.range_threshold = range_threshold
        self._pending_cap = pending_size if pending_size is not None else capacity
        self._store: OrderedDict[str, int] = OrderedDict()
        self._pending: OrderedDict[str, Tuple[int, int]] = OrderedDict()
        self._mode = 0
        self._pressure_window = pressure_window
        self._high_evict = high_evict
        self._low_evict = low_evict
        self._weak_hit = weak_hit
        self._strong_hit = strong_hit
        self._w_ops = 0
        self._w_hits = 0
        self._w_evicts = 0

    def _bump_window(self, hit: bool, evicted: bool):
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

    def process(self, key: str, new_qs: int, ts: int = 0) -> Tuple[bool, bool]:
        if key in self._store:
            cached = self._store[key]
            self._store.move_to_end(key)
            hit = abs(new_qs - cached) <= self.range_threshold
            if not hit:
                self._store[key] = new_qs
            self._bump_window(hit, False)
            return hit, False
        if self._mode == 0:
            evicted = False
            if len(self._store) >= self.capacity:
                self._store.popitem(last=False)
                evicted = True
            self._store[key] = new_qs
            self._bump_window(False, evicted)
            return False, evicted
        prev_qs, touches = self._pending.pop(key, (new_qs, 0))
        touches += 1
        required_touches = 1 if self._mode == 1 else 2
        if touches <= required_touches:
            if len(self._pending) >= self._pending_cap:
                self._pending.popitem(last=False)
            self._pending[key] = (new_qs, touches)
            self._bump_window(False, False)
            return False, False
        evicted = False
        if len(self._store) >= self.capacity:
            self._store.popitem(last=False)
            evicted = True
        self._store[key] = new_qs
        self._bump_window(False, evicted)
        return False, evicted


class TimingBloomQS:
    """LRU with timing Bloom admission. Gates admission under eviction pressure."""
    name = "TimeLimitedBloomLRU"

    def __init__(self, capacity: int, range_threshold: int = 0, bloom_bits=1 << 18,
                 bloom_hashes=4, bloom_epoch_records=256, pressure_window=10000,
                 eviction_high_watermark=0.02):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        self.capacity = capacity
        self.range_threshold = range_threshold
        self._store: OrderedDict[str, int] = OrderedDict()
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

    def _update_pressure(self, evicted: bool):
        self._window_ops += 1
        if evicted:
            self._window_evicts += 1
        if self._window_ops >= self._pressure_window:
            ratio = self._window_evicts / self._window_ops
            self._under_pressure = ratio >= self._evict_high_watermark
            self._window_ops = 0
            self._window_evicts = 0

    def process(self, key: str, new_qs: int, ts: int = 0) -> Tuple[bool, bool]:
        self._tick()
        if key in self._store:
            cached = self._store[key]
            self._store.move_to_end(key)
            hit = abs(new_qs - cached) <= self.range_threshold
            if not hit:
                self._store[key] = new_qs
            self._update_pressure(False)
            return hit, False
        seen_recently = self._bloom.contains(key)
        self._bloom.add(key)
        gate_admission = (len(self._store) >= self.capacity) and self._under_pressure
        if gate_admission and not seen_recently:
            self._update_pressure(False)
            return False, False
        evicted = False
        if len(self._store) >= self.capacity:
            self._store.popitem(last=False)
            evicted = True
        self._store[key] = new_qs
        self._update_pressure(evicted)
        return False, evicted


class _TinyLFUSketch:
    def __init__(self, sample_size, counter_cap):
        if sample_size <= 0:
            raise ValueError("sample_size must be > 0")
        if counter_cap <= 0:
            raise ValueError("counter_cap must be > 0")
        self.sample_size = sample_size
        self.counter_cap = counter_cap
        self._ops = 0
        self._counts: Dict[str, int] = {}
        self._doorkeeper: set = set()

    def _reset(self):
        self._counts = {k: v // 2 for k, v in self._counts.items() if v // 2 > 0}
        self._doorkeeper.clear()
        self._ops = 0

    def observe(self, key: str):
        self._ops += 1
        if key in self._doorkeeper:
            nxt = self._counts.get(key, 0) + 1
            self._counts[key] = min(nxt, self.counter_cap)
        else:
            self._doorkeeper.add(key)
        if self._ops >= self.sample_size:
            self._reset()

    def estimate(self, key: str) -> int:
        return self._counts.get(key, 0) + (1 if key in self._doorkeeper else 0)


class TinyLFUQS:
    """LRU eviction with TinyLFU admission. Admits candidate only if more frequent than victim."""
    name = "TinyLFULRU"

    def __init__(self, capacity: int, range_threshold: int = 0, sample_multiplier: int = 8):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        self.capacity = capacity
        self.range_threshold = range_threshold
        self._store: OrderedDict[str, int] = OrderedDict()
        sample_size = max(capacity, int(capacity * sample_multiplier))
        counter_cap = max(1, sample_size // capacity)
        self._sketch = _TinyLFUSketch(sample_size=sample_size, counter_cap=counter_cap)

    def process(self, key: str, new_qs: int, ts: int = 0) -> Tuple[bool, bool]:
        self._sketch.observe(key)
        if key in self._store:
            cached = self._store[key]
            self._store.move_to_end(key)
            if abs(new_qs - cached) <= self.range_threshold:
                return True, False
            self._store[key] = new_qs
            return False, False
        if len(self._store) < self.capacity:
            self._store[key] = new_qs
            return False, False
        victim_key = next(iter(self._store))
        if self._sketch.estimate(key) > self._sketch.estimate(victim_key):
            self._store.popitem(last=False)
            self._store[key] = new_qs
            return False, True
        return False, False


class _TinyCacheTable:
    def __init__(self, set_count, set_capacity, duplicate_cap, fingerprint_bits=16, seed=0):
        if set_count <= 0:
            raise ValueError("set_count must be > 0")
        if set_capacity <= 0:
            raise ValueError("set_capacity must be > 0")
        if duplicate_cap <= 0:
            raise ValueError("duplicate_cap must be > 0")
        self.set_count = set_count
        self.set_capacity = set_capacity
        self.duplicate_cap = duplicate_cap
        self.fingerprint_bits = fingerprint_bits
        self._mask = (1 << fingerprint_bits) - 1
        self._rng = random.Random(seed)
        self._sets: List[List] = [[] for _ in range(set_count)]
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
            self._sets[idx] = [fp for fp in bucket if self._rng.random() < 0.5]

    def estimate(self, key):
        fingerprint = self._fingerprint(key)
        bucket = self._sets[self._set_index(key)]
        return self._bucket_count(bucket, fingerprint)


class TinyCacheQS:
    """LRU eviction with TinyCache admission filter."""
    name = "TinyCacheLRU"

    def __init__(self, capacity: int, range_threshold: int = 0, sample_multiplier=8,
                 set_count=None, duplicate_cap=None, fingerprint_bits=16):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        self.capacity = capacity
        self.range_threshold = range_threshold
        self._store: OrderedDict[str, int] = OrderedDict()
        self._set_count = set_count if set_count is not None else max(1, capacity)
        self._set_capacity = max(1, sample_multiplier)
        self._duplicate_cap = duplicate_cap if duplicate_cap is not None else max(1, self._set_capacity // 2)
        self._table = _TinyCacheTable(
            set_count=self._set_count,
            set_capacity=self._set_capacity,
            duplicate_cap=self._duplicate_cap,
            fingerprint_bits=fingerprint_bits,
        )

    def process(self, key: str, new_qs: int, ts: int = 0) -> Tuple[bool, bool]:
        self._table.observe(key)
        if key in self._store:
            cached = self._store[key]
            self._store.move_to_end(key)
            if abs(new_qs - cached) <= self.range_threshold:
                return True, False
            self._store[key] = new_qs
            return False, False
        if len(self._store) < self.capacity:
            self._store[key] = new_qs
            return False, False
        victim_key = next(iter(self._store))
        if self._table.estimate(key) >= self._table.estimate(victim_key):
            self._store.popitem(last=False)
            self._store[key] = new_qs
            return False, True
        return False, False


class SegmentedQS:
    """2-segment LRU (SLRU). Probation + protected, total N slots."""
    name = "SegmentedLRU"

    def __init__(self, capacity: int, range_threshold: int = 0):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        self.capacity = capacity
        self.range_threshold = range_threshold
        self._prob_cap = max(1, capacity // 4)
        self._prot_cap = capacity - self._prob_cap
        self._probation: OrderedDict[str, int] = OrderedDict()
        self._protected: OrderedDict[str, int] = OrderedDict()

    def process(self, key: str, new_qs: int, ts: int = 0) -> Tuple[bool, bool]:
        if key in self._protected:
            cached = self._protected[key]
            self._protected.move_to_end(key)
            if abs(new_qs - cached) <= self.range_threshold:
                return True, False
            self._protected[key] = new_qs
            return False, False
        if key in self._probation:
            cached = self._probation.pop(key)
            hit = abs(new_qs - cached) <= self.range_threshold
            if self._prot_cap == 0:
                self._probation[key] = new_qs
                return hit, False
            if len(self._protected) >= self._prot_cap:
                dem_key, dem_qs = self._protected.popitem(last=False)
                self._probation[dem_key] = dem_qs
            self._protected[key] = new_qs
            return hit, False
        evicted = False
        if len(self._probation) >= self._prob_cap:
            self._probation.popitem(last=False)
            evicted = True
        self._probation[key] = new_qs
        return False, evicted


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def simulate_congestion(records: List[Dict], cache, oracle=None,
                        capacity_samples=None, capacity_sample_every: int = 1000) -> CongestResult:
    """
    Replay records through cache.  If oracle is supplied (an InfiniteQS instance),
    classify each miss as necessary or redundant.  If oracle is None, every miss
    counts as necessary (use only for unbounded caches that are their own oracle).
    """
    result = CongestResult(cache_name=cache.name, capacity=cache.capacity)

    track_capacity = capacity_samples is not None and cache.capacity != float('inf')
    sample_every = max(1, int(capacity_sample_every))
    last_ts = 0

    for rec in records:
        result.total += 1
        key = rec["source"]
        new_qs = rec["qs"]
        ts = rec.get("ts_ps", 0)
        last_ts = ts

        hit, evicted = cache.process(key, new_qs, ts)
        if evicted:
            result.evictions += 1

        if hit:
            result.hits += 1
        else:
            if oracle is None:
                # Unbounded cache is its own oracle: every forward is necessary.
                result.necessary_forwards += 1
                result.new_route_forwards += 1
            else:
                key_is_new = key not in oracle._first_seen
                oracle_hit, _ = oracle.process(key, new_qs, ts)
                if oracle_hit:
                    # Oracle suppresses but bounded cache lost track — redundant.
                    result.redundant_forwards += 1
                else:
                    # Oracle also forwards: genuinely new key or value changed beyond threshold.
                    result.necessary_forwards += 1
                    if key_is_new:
                        result.new_route_forwards += 1
                    else:
                        result.route_change_forwards += 1

        if track_capacity and (result.total == 1 or result.total % sample_every == 0):
            assert capacity_samples is not None
            slots = cache_slots_used(cache)
            if slots is not None:
                capacity_samples.append((result.total, ts, slots))

    if track_capacity and result.total > 0:
        assert capacity_samples is not None
        slots = cache_slots_used(cache)
        if slots is not None and (not capacity_samples or capacity_samples[-1][0] != result.total):
            capacity_samples.append((result.total, last_ts, slots))

    return result


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------

SWEEP_SIZES = [4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096]


def sweep(records: List[Dict], range_threshold: int, capacity_curves=None,
          capacity_sample_every: int = 1000) -> List[CongestResult]:
    results: List[CongestResult] = []

    # Unbounded baseline
    results.append(simulate_congestion(records, InfiniteQS(range_threshold)))

    TTL_SWEEP = {
        "0.1ms":   100_000_000,
        "0.5ms":   500_000_000,
        "2ms":   2_000_000_000,
        "10ms": 10_000_000_000,
    }

    for size in SWEEP_SIZES:
        rt = range_threshold
        for factory in [
            lambda s=size, r=rt: LRUQSCache(s, r),
            lambda s=size, r=rt: FIFOQSCache(s, r),
            lambda s=size, r=rt: LFUQSCache(s, r),
            lambda s=size, r=rt: TinyLFUQS(s, r),
            lambda s=size, r=rt: TinyCacheQS(s, r),
            lambda s=size, r=rt: AdmissionFilterQS(s, r),
            lambda s=size, r=rt: PendingAdmissionQS(s, r),
            lambda s=size, r=rt: PITCollapsedQS(s, r),
            lambda s=size, r=rt: AdaptiveAdmissionQS(s, r),
            lambda s=size, r=rt: OnlineAdaptiveAdmissionQS(s, r),
            lambda s=size, r=rt: TimingBloomQS(s, r),
            lambda s=size, r=rt: FreshnessInvalidationQS(s, r),
            lambda s=size, r=rt: CacheINTFreshnessQS(s, r),
            lambda s=size, r=rt: FlowLifetimeAdaptiveTTLQS(s, r),
            lambda s=size, r=rt: SegmentedQS(s, r),
        ]:
            cache = factory()
            oracle = InfiniteQS(range_threshold)
            samples = [] if capacity_curves is not None else None
            result = simulate_congestion(records, cache, oracle, samples, capacity_sample_every)
            if capacity_curves is not None and samples:
                capacity_curves[(result.cache_name, int(result.capacity))] = samples
            results.append(result)

        for label, ttl_ps in TTL_SWEEP.items():
            cache = LRUQSCacheTTL(size, range_threshold, ttl_ps)
            oracle = InfiniteQS(range_threshold)
            samples = [] if capacity_curves is not None else None
            result = simulate_congestion(records, cache, oracle, samples, capacity_sample_every)
            result.cache_name = f"LRUTtl({label})"
            if capacity_curves is not None and samples:
                capacity_curves[(result.cache_name, int(result.capacity))] = samples
            results.append(result)

    return results


# ---------------------------------------------------------------------------
# Record extraction
# ---------------------------------------------------------------------------

def build_hop_records(logfile: Path, args: argparse.Namespace) -> Tuple[List[Dict], int]:
    """Return (hop_records, total_int_records).

    Extracts every (switch, queue_size) observation from every INT hop in the trace.
    No pre-filtering: all hops contribute; detection happens inside the cache simulation.
    """
    records: List[Dict] = []
    n_int = 0
    for rec in parse(str(logfile)):
        n_int += 1
        if args.max_records > 0 and n_int > args.max_records:
            break
        sw = rec.get("sw", [])
        typ = rec.get("typ", [])
        qs = rec.get("qs", [])
        ts = rec.get("ts", [])
        if args.key_level == "switch":
            for i in range(min(len(sw), len(typ), len(qs), len(ts))):
                records.append({
                    "source": f"{sw[i]}:{typ[i]}",
                    "qs": int(qs[i]),
                    "ts_ps": int(ts[i]),
                })
        else:
            flow = rec.get("flow", 0)
            if qs:
                max_qs = int(max(qs[:len(sw)]))
                records.append({
                    "source": str(flow),
                    "qs": max_qs,
                    "ts_ps": int(ts[-1]) if ts else 0,
                })
    return records, n_int


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_results(results: List[CongestResult]) -> None:
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


def write_csv(results: List[CongestResult], path: str) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cache", "capacity", "total", "hits", "suppression_rate",
                    "forwards", "forward_rate", "necessary_forwards",
                    "new_route_forwards", "route_change_forwards",
                    "redundant_forwards", "redundancy_rate", "evictions"])
        for r in results:
            cap = r.capacity if r.capacity != float('inf') else -1
            w.writerow([r.cache_name, cap, r.total, r.hits,
                        round(r.suppression_rate, 4),
                        r.forwards, round(r.forward_rate, 4),
                        r.necessary_forwards, r.new_route_forwards,
                        r.route_change_forwards, r.redundant_forwards,
                        round(r.redundancy_rate, 4), r.evictions])
    print(f"\nCSV written to {path}", file=sys.stderr)


def write_capacity_csv(capacity_curves, path: str) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cache", "capacity", "record_index", "timestamp_ps",
                    "slots_used", "fill_ratio", "fill_percent"])
        for (cache_name, capacity) in sorted(capacity_curves.keys(), key=lambda k: (k[0], k[1])):
            if capacity <= 0 or math.isinf(capacity):
                continue
            for rec_idx, ts_ps, slots_used in capacity_curves[(cache_name, capacity)]:
                fill_ratio = min(1.0, max(0.0, slots_used / capacity))
                w.writerow([cache_name, capacity, rec_idx, ts_ps, slots_used,
                             round(fill_ratio, 6), round(fill_ratio * 100.0, 4)])
    print(f"\nCapacity CSV written to {path}", file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input_path", help="Synthetic INT logfile path or directory")
    parser.add_argument("--pattern", default="*.txt",
                        help="Glob when input_path is a directory (default: %(default)s)")
    parser.add_argument("--max-records", type=int, default=0,
                        help="Only parse first N INT packets (0 means all)")
    parser.add_argument("--range-threshold", type=int, default=8192,
                        help=("Forward a report when |new_qs - cached_qs| > N bytes. "
                              "0 = forward every reading. (default: %(default)s)"))
    parser.add_argument("--key-level", choices=["switch", "flow"], default="switch",
                        help="Cache key: 'switch' uses (switch_id, switch_type); 'flow' uses flow_id")
    parser.add_argument("--sweep", action="store_true", help="Sweep all policies/sizes")
    parser.add_argument("--cache",
                        choices=["lru", "fifo", "lfu", "lru_ttl", "f_inv", "cache_int",
                                 "life_ttl", "admission", "pending_admission", "pit",
                                 "adaptive", "online_adaptive", "bloom", "tiny_lfu",
                                 "tiny_cache", "segmented", "infinite"],
                        default="lru", help="Cache policy for single run")
    parser.add_argument("--size", type=int, default=64, help="Cache capacity for single run")
    parser.add_argument("--ttl-ms", type=float, default=10.0,
                        help="Keep-alive TTL in milliseconds for LRUTTL (default 10ms)")
    parser.add_argument("--fresh-ttl-ms", type=float, default=2.0,
                        help="Freshness TTL in milliseconds for FreshnessInvalidationLRU (default 2ms)")
    parser.add_argument("--dual-dyn-ttl-ms", type=float, default=0.5,
                        help="Dynamic-class TTL in ms for CacheINTFreshnessLRU (default 0.5ms)")
    parser.add_argument("--dual-stable-hits", type=int, default=3,
                        help="Stable hits needed to promote to static class in CacheINTFreshnessLRU")
    parser.add_argument("--pit-download-us", type=float, default=2.0,
                        help="PIT download delay in microseconds for PITCollapsedLRU (default 2us)")
    parser.add_argument("--life-min-ttl-ms", type=float, default=0.1)
    parser.add_argument("--life-max-ttl-ms", type=float, default=20.0)
    parser.add_argument("--life-base-ttl-ms", type=float, default=0.5)
    parser.add_argument("--life-ema-alpha", type=float, default=0.2)
    parser.add_argument("--life-ttl-multiplier", type=float, default=4.0)
    parser.add_argument("--bloom-bits", type=int, default=1 << 18)
    parser.add_argument("--bloom-hashes", type=int, default=4)
    parser.add_argument("--bloom-epoch-records", type=int, default=256)
    parser.add_argument("--pending-reset-every", type=int, default=0)
    parser.add_argument("--csv", metavar="FILE", help="Write results to CSV file")
    parser.add_argument("--capacity-csv", metavar="FILE",
                        help="Write cache occupancy samples over time to CSV file")
    parser.add_argument("--capacity-sample-every", type=int, default=1000,
                        help="Record one capacity sample every N hops (default: 1000)")
    parser.add_argument("--fast", action="store_true",
                        help="(No-op — kept for interface consistency)")
    parser.add_argument("--quiet-table", action="store_true",
                        help="Suppress printing the results table to stdout")
    return parser.parse_args()


def resolve_inputs(input_path: Path, pattern: str) -> List[Path]:
    if input_path.is_file():
        return [input_path]
    if not input_path.is_dir():
        raise FileNotFoundError(f"Input path does not exist: {input_path}")
    files = sorted([p for p in input_path.glob(pattern) if p.is_file()], key=lambda p: p.name)
    if not files:
        raise FileNotFoundError(f"No files matching {pattern} under {input_path}")
    return files


def main() -> None:  # pragma: no cover
    args = parse_args()
    input_path = Path(args.input_path)
    files = resolve_inputs(input_path, args.pattern)

    all_records: List[Dict] = []
    total_int = 0
    for idx, path in enumerate(files, start=1):
        if len(files) > 1:
            print(f"Loading {idx}/{len(files)}: {path.name}", file=sys.stderr)
        recs, n = build_hop_records(path, args)
        all_records.extend(recs)
        total_int += n

    print(
        f"Parsed {total_int:,} INT records → {len(all_records):,} hop observations "
        f"(range threshold: {args.range_threshold} bytes)",
        file=sys.stderr,
    )

    ttl_ps = int(args.ttl_ms * 1_000_000_000)
    fresh_ttl_ps = int(args.fresh_ttl_ms * 1_000_000_000)
    dual_dyn_ttl_ps = int(args.dual_dyn_ttl_ms * 1_000_000_000)
    pit_download_ps = int(args.pit_download_us * 1_000_000)
    life_min_ttl_ps = int(args.life_min_ttl_ms * 1_000_000_000)
    life_max_ttl_ps = int(args.life_max_ttl_ms * 1_000_000_000)
    life_base_ttl_ps = int(args.life_base_ttl_ms * 1_000_000_000)
    rt = args.range_threshold

    if args.sweep:
        capacity_curves = {} if args.capacity_csv else None
        results = sweep(all_records, rt, capacity_curves, args.capacity_sample_every)
        if not args.quiet_table:
            print_results(results)
        if args.csv:
            write_csv(results, args.csv)
        if args.capacity_csv and capacity_curves is not None:
            write_capacity_csv(capacity_curves, args.capacity_csv)
        return

    cache_map = {
        "lru":              lambda: LRUQSCache(args.size, rt),
        "fifo":             lambda: FIFOQSCache(args.size, rt),
        "lfu":              lambda: LFUQSCache(args.size, rt),
        "lru_ttl":          lambda: LRUQSCacheTTL(args.size, rt, ttl_ps),
        "f_inv":            lambda: FreshnessInvalidationQS(args.size, rt, fresh_ttl_ps),
        "cache_int":        lambda: CacheINTFreshnessQS(args.size, rt, dual_dyn_ttl_ps, args.dual_stable_hits),
        "life_ttl":         lambda: FlowLifetimeAdaptiveTTLQS(
            args.size, rt, life_min_ttl_ps, life_max_ttl_ps, life_base_ttl_ps,
            args.life_ema_alpha, args.life_ttl_multiplier,
        ),
        "admission":        lambda: AdmissionFilterQS(
            args.size, rt, pending_reset_every=args.bloom_epoch_records,
            bloom_bits=args.bloom_bits, bloom_hashes=args.bloom_hashes,
        ),
        "pending_admission": lambda: PendingAdmissionQS(args.size, rt, pending_reset_every=args.pending_reset_every),
        "pit":              lambda: PITCollapsedQS(args.size, rt, pit_download_ps),
        "adaptive":         lambda: AdaptiveAdmissionQS(args.size, rt, pending_reset_every=args.pending_reset_every),
        "online_adaptive":  lambda: OnlineAdaptiveAdmissionQS(args.size, rt),
        "bloom":            lambda: TimingBloomQS(args.size, rt, args.bloom_bits, args.bloom_hashes, args.bloom_epoch_records),
        "tiny_lfu":         lambda: TinyLFUQS(args.size, rt),
        "tiny_cache":       lambda: TinyCacheQS(args.size, rt),
        "segmented":        lambda: SegmentedQS(args.size, rt),
        "infinite":         lambda: InfiniteQS(rt),
    }
    cache = cache_map[args.cache]()
    unbounded = args.cache == "infinite"
    oracle = None if unbounded else InfiniteQS(rt)
    cap_samples = [] if args.capacity_csv else None
    result = simulate_congestion(all_records, cache, oracle, cap_samples, args.capacity_sample_every)
    print(result)
    if args.capacity_csv and cap_samples and result.capacity != float('inf'):
        write_capacity_csv({(result.cache_name, int(result.capacity)): cap_samples}, args.capacity_csv)


if __name__ == "__main__":
    main()
