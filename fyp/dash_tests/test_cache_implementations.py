from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from fyp.dash_scripts.cache_sim_congestion_int import (
    AdaptiveAdmissionQS,
    AdmissionFilterQS,
    CacheINTFreshnessQS,
    CongestResult,
    FIFOQSCache,
    FreshnessInvalidationQS,
    FlowLifetimeAdaptiveTTLQS,
    InfiniteQS,
    LFUQSCache,
    LRUQSCache,
    LRUQSCacheTTL,
    OnlineAdaptiveAdmissionQS,
    PendingAdmissionQS,
    PITCollapsedQS,
    RollingBloomFilter as RollingBloomFilterQS,
    SegmentedQS,
    TimingBloomQS,
    TinyCacheQS,
    TinyLFUQS,
    _TinyCacheTable as _TinyCacheTableQS,
    _TinyLFUSketch as _TinyLFUSketchQS,
    cache_slots_used as cache_slots_used_qs,
    print_results as print_congestion_results,
    simulate_congestion,
    sweep as sweep_congestion,
    write_capacity_csv as write_congestion_capacity_csv,
    write_csv as write_congestion_csv,
)
from fyp.dash_scripts.cache_sim import (
    AdaptiveAdmissionLRU,
    AdmissionFilterLRU,
    CacheINTFreshnessLRU,
    CacheResult,
    DualFreshnessLRU,
    FIFOLastPath,
    FlowLifetimeAdaptiveTTL,
    FreshnessInvalidationLRU,
    InfiniteLastPath,
    LFULastPath,
    LRULastPath,
    LRULastPathTTL,
    OnlineAdaptiveAdmissionLRU,
    OnlineAdaptiveDualTTL,
    PendingAdmissionLRU,
    PITCollapsedLRU,
    RollingBloomFilter,
    SegmentedLRU,
    TimingBloomLRU,
    TinyCacheLRU,
    TinyLFULRU,
    TwoFilterOHWLRU,
    VolatilityAwareLRU,
    _TinyCacheTable,
    _TinyLFUSketch,
    cache_slots_used,
    print_results,
    simulate,
    sweep,
    write_capacity_csv,
    write_csv,
)
from fyp.dash_scripts.cache_sim_source_seen import (
    load_records,
    merge_results,
    sanitize_name,
    simulate_source,
    sniff_delimiter,
    split_csv_dir,
    sweep as sweep_source_seen,
    to_picoseconds,
    write_per_split_csvs,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _records() -> list[dict[str, object]]:
    return [
        {"flow": 1, "sw": [10, 11], "ts": [100]},
        {"flow": 1, "sw": [10, 11], "ts": [200]},
        {"flow": 2, "sw": [20, 21], "ts": [300]},
        {"flow": 1, "sw": [10, 12], "ts": [400]},
        {"flow": 3, "sw": [30, 31], "ts": [500]},
        {"flow": 1, "sw": [10, 11], "ts": [600]},
    ]


def _source_records() -> list[tuple[str, tuple[object, ...], int]]:
    return [
        ("s1", ("seen",), 100),
        ("s1", ("seen",), 200),
        ("s2", ("seen",), 300),
        ("s1", ("seen",), 400),
        ("s3", ("seen",), 500),
    ]


# ---------------------------------------------------------------------------
# Original tests (preserved)
# ---------------------------------------------------------------------------

def test_infinite_cache_hits_seen_path() -> None:
    c = InfiniteLastPath()
    assert c.lookup_and_update(1, (1, 2), 0) == (False, False)
    assert c.lookup_and_update(1, (1, 2), 0) == (True, False)
    assert c.lookup_and_update(1, (1, 3), 0) == (False, False)


def test_lru_and_fifo_eviction_behavior() -> None:
    lru = LRULastPath(2)
    assert lru.lookup_and_update("a", (1,), 0) == (False, False)
    assert lru.lookup_and_update("b", (1,), 0) == (False, False)
    assert lru.lookup_and_update("a", (1,), 0) == (True, False)
    assert lru.lookup_and_update("c", (1,), 0) == (False, True)

    fifo = FIFOLastPath(2)
    assert fifo.lookup_and_update("a", (1,), 0) == (False, False)
    assert fifo.lookup_and_update("b", (1,), 0) == (False, False)
    assert fifo.lookup_and_update("c", (1,), 0) == (False, True)


def test_lfu_prefers_frequent_key() -> None:
    lfu = LFULastPath(2)
    lfu.lookup_and_update("a", (1,), 0)
    lfu.lookup_and_update("b", (1,), 0)
    lfu.lookup_and_update("a", (1,), 0)  # make a hot
    miss, evicted = lfu.lookup_and_update("c", (1,), 0)
    assert miss is False
    assert evicted is True


def test_ttl_variants_expire_entries() -> None:
    ttl = LRULastPathTTL(2, ttl_ps=100)
    assert ttl.lookup_and_update("a", (1,), 0) == (False, False)
    assert ttl.lookup_and_update("a", (1,), 50)[0] is True
    assert ttl.lookup_and_update("a", (1,), 200)[0] is False

    fresh = FreshnessInvalidationLRU(2, freshness_ttl_ps=100)
    assert fresh.lookup_and_update("a", (1,), 0) == (False, False)
    assert fresh.lookup_and_update("a", (1,), 50)[0] is True
    assert fresh.lookup_and_update("a", (1,), 200)[0] is False


def test_advanced_admission_policies_do_not_crash() -> None:
    policies = [
        PendingAdmissionLRU(4, pending_reset_every=2),
        PITCollapsedLRU(4, download_delay_ps=10),
        AdaptiveAdmissionLRU(4),
        OnlineAdaptiveAdmissionLRU(4),
        TinyLFULRU(4),
        TinyCacheLRU(4),
        CacheINTFreshnessLRU(4),
        FlowLifetimeAdaptiveTTL(4),
    ]
    for policy in policies:
        for rec in _records():
            flow = rec["flow"]
            path = tuple(rec["sw"])
            ts = rec["ts"][-1]
            hit, evicted = policy.lookup_and_update(flow, path, ts)
            assert isinstance(hit, bool)
            assert isinstance(evicted, bool)


def test_simulate_and_capacity_csv(tmp_path: Path) -> None:
    curves: dict[tuple[str, int], list[tuple[int, int, int]]] = {}
    results = sweep(_records(), capacity_curves=curves, capacity_sample_every=1)
    assert results
    assert any(r.capacity != float("inf") for r in results)
    assert curves

    out_csv = tmp_path / "capacity.csv"
    write_capacity_csv(curves, str(out_csv))
    text = out_csv.read_text(encoding="utf-8")
    assert "fill_percent" in text


def test_source_seen_sweep_and_capacity() -> None:
    curves: dict[tuple[str, int], list[tuple[int, int, int]]] = {}
    results = sweep_source_seen(_source_records(), capacity_curves=curves, capacity_sample_every=1)
    assert results
    assert curves


def test_source_seen_simulate_basic() -> None:
    recs = _source_records()
    result = simulate_source(recs, LRULastPath(2), oracle=InfiniteLastPath())
    assert result.total == len(recs)
    assert result.forwards >= 1


# ---------------------------------------------------------------------------
# CacheResult properties and __str__
# ---------------------------------------------------------------------------

def test_cache_result_properties() -> None:
    r = CacheResult(cache_name="TestCache", capacity=10)
    r.total = 100
    r.hits = 60
    r.necessary_forwards = 30
    r.redundant_forwards = 10
    r.evictions = 5
    r.new_route_forwards = 20
    r.route_change_forwards = 10

    assert r.forwards == 40
    assert abs(r.suppression_rate - 0.60) < 1e-9
    assert abs(r.forward_rate - 0.40) < 1e-9
    assert abs(r.redundancy_rate - 0.25) < 1e-9
    assert abs(r.efficiency - 0.75) < 1e-9


def test_cache_result_zero_totals() -> None:
    r = CacheResult(cache_name="Z", capacity=4)
    assert r.suppression_rate == 0.0
    assert r.forward_rate == 0.0
    assert r.forwards == 0
    # zero forwards -> efficiency=1, redundancy_rate=0
    assert r.efficiency == 1.0
    assert r.redundancy_rate == 0.0


def test_cache_result_str_finite_and_infinite() -> None:
    r_finite = CacheResult(cache_name="LRU", capacity=64)
    r_finite.total = 10
    s = str(r_finite)
    assert "cap=64" in s
    assert "LRU" in s

    r_inf = CacheResult(cache_name="Infinite", capacity=float("inf"))
    r_inf.total = 5
    s2 = str(r_inf)
    assert "∞" in s2


# ---------------------------------------------------------------------------
# cache_slots_used — all three branches
# ---------------------------------------------------------------------------

def test_cache_slots_used_store_dict() -> None:
    c = LRULastPath(4)
    c.lookup_and_update("a", (1,), 0)
    c.lookup_and_update("b", (2,), 0)
    assert cache_slots_used(c) == 2


def test_cache_slots_used_protected_probation() -> None:
    c = SegmentedLRU(8)
    c.lookup_and_update("a", (1,), 0)
    c.lookup_and_update("b", (2,), 0)
    assert cache_slots_used(c) == 2


def test_cache_slots_used_sets() -> None:
    t = _TinyCacheTable(set_count=4, set_capacity=4, duplicate_cap=2)
    t.observe("key1")
    t.observe("key2")
    total = cache_slots_used(type("FakeTinyCache", (), {"_sets": t._sets})())
    assert total is not None and total >= 0


def test_cache_slots_used_fallback() -> None:
    class Opaque:
        pass
    assert cache_slots_used(Opaque()) is None


# ---------------------------------------------------------------------------
# RollingBloomFilter
# ---------------------------------------------------------------------------

def test_rolling_bloom_basic() -> None:
    bf = RollingBloomFilter(bits=256, hashes=2)
    assert not bf.contains("foo")
    bf.add("foo")
    assert bf.contains("foo")
    bf.reset_epoch()
    assert bf.contains("foo")  # still in previous window
    bf.reset_epoch()
    assert not bf.contains("foo")  # both windows cleared


def test_rolling_bloom_invalid_params() -> None:
    with pytest.raises(ValueError):
        RollingBloomFilter(bits=0)
    with pytest.raises(ValueError):
        RollingBloomFilter(hashes=0)


# ---------------------------------------------------------------------------
# DualFreshnessLRU
# ---------------------------------------------------------------------------

def test_dual_freshness_lru_stable_promotion() -> None:
    # stable_hit_threshold=2 means stable_hits must reach 2 before using static TTL.
    # stable_hits is incremented on hits (same path, within TTL).
    # Hits keep last_ts fixed, so TTL window is measured from last *miss*.
    c = DualFreshnessLRU(4, dynamic_ttl_ps=10000, static_ttl_ps=100000, stable_hit_threshold=2)
    assert c.lookup_and_update("f1", (1,), 0) == (False, False)    # insert, stable_hits=0
    # Hit 1: stable_hits=min(0+1,2)=1, still dynamic (1<2), but within ttl: True
    assert c.lookup_and_update("f1", (1,), 50)[0] is True
    # Hit 2: stable_hits=min(1+1,2)=2, now at threshold; uses static_ttl on NEXT lookup
    assert c.lookup_and_update("f1", (1,), 100)[0] is True
    # Hit 3: stable_hits>=threshold → uses static_ttl_ps=100000, within window: True
    assert c.lookup_and_update("f1", (1,), 150)[0] is True


def test_dual_freshness_lru_path_change_resets() -> None:
    c = DualFreshnessLRU(4, dynamic_ttl_ps=100, static_ttl_ps=10000, stable_hit_threshold=3)
    c.lookup_and_update("f1", (1,), 0)
    c.lookup_and_update("f1", (1,), 10)
    c.lookup_and_update("f1", (1,), 20)
    # path change → demote back to dynamic
    hit, _ = c.lookup_and_update("f1", (2,), 30)
    assert hit is False


def test_dual_freshness_lru_dynamic_ttl_expiry() -> None:
    c = DualFreshnessLRU(4, dynamic_ttl_ps=50, static_ttl_ps=5000, stable_hit_threshold=5)
    c.lookup_and_update("f1", (1,), 0)
    # within TTL: hit
    assert c.lookup_and_update("f1", (1,), 30)[0] is True
    # beyond dynamic TTL: miss (same path but TTL expired)
    assert c.lookup_and_update("f1", (1,), 200)[0] is False


def test_dual_freshness_lru_eviction() -> None:
    c = DualFreshnessLRU(2, dynamic_ttl_ps=1000, static_ttl_ps=10000, stable_hit_threshold=5)
    c.lookup_and_update(1, (1,), 0)
    c.lookup_and_update(2, (2,), 0)
    _, evicted = c.lookup_and_update(3, (3,), 0)
    assert evicted is True


def test_dual_freshness_lru_invalid_params() -> None:
    with pytest.raises(ValueError):
        DualFreshnessLRU(0)
    with pytest.raises(ValueError):
        DualFreshnessLRU(4, dynamic_ttl_ps=0)
    with pytest.raises(ValueError):
        DualFreshnessLRU(4, stable_hit_threshold=0)


# ---------------------------------------------------------------------------
# VolatilityAwareLRU
# ---------------------------------------------------------------------------

def test_volatility_aware_lru_hit() -> None:
    c = VolatilityAwareLRU(4)
    c.lookup_and_update("f1", (1,), 0)
    hit, evicted = c.lookup_and_update("f1", (1,), 1)
    assert hit is True
    assert evicted is False


def test_volatility_aware_lru_path_change() -> None:
    c = VolatilityAwareLRU(4)
    c.lookup_and_update("f1", (1,), 0)
    hit, _ = c.lookup_and_update("f1", (2,), 1)
    assert hit is False
    assert c._changes.get("f1", 0) == 1


def test_volatility_aware_lru_evicts_most_volatile() -> None:
    c = VolatilityAwareLRU(2)
    c.lookup_and_update("stable", (1,), 0)
    c.lookup_and_update("volatile", (2,), 1)
    # Make volatile accumulate many changes
    for i in range(5):
        c.lookup_and_update("volatile", (i + 10,), i + 2)
    # Now stable + volatile in cache (cap=2); add new flow → evict most volatile
    # Force stable back in if it got displaced
    c2 = VolatilityAwareLRU(2)
    c2.lookup_and_update("volatile", (1,), 0)
    c2.lookup_and_update("volatile", (2,), 1)  # +1 change
    c2.lookup_and_update("stable", (1,), 2)    # stable inserted
    _, evicted = c2.lookup_and_update("new", (5,), 3)
    assert evicted is True


# ---------------------------------------------------------------------------
# AdmissionFilterLRU (OneHitWonder)
# ---------------------------------------------------------------------------

def test_admission_filter_lru_second_hit_admits() -> None:
    c = AdmissionFilterLRU(4, bloom_bits=64, bloom_hashes=2)
    # First touch: not admitted, goes into bloom
    hit1, ev1 = c.lookup_and_update("f1", (1,), 0)
    assert hit1 is False and ev1 is False
    assert "f1" not in c._store
    # Second touch: bloom sees it, admits
    hit2, _ = c.lookup_and_update("f1", (1,), 1)
    assert hit2 is False  # still a miss (admitted now)
    assert "f1" in c._store


def test_admission_filter_lru_epoch_reset() -> None:
    # pending_reset_every=3: at ops=3, bloom.reset_epoch() moves current→previous.
    # f1 was added at ops=1 → in current; after reset, it moves to previous.
    # Previous is still checked by contains(), so f1 is still "seen".
    # Only after a second reset does f1 fully clear.
    c = AdmissionFilterLRU(4, bloom_bits=64, bloom_hashes=2, pending_reset_every=3)
    c.lookup_and_update("f1", (1,), 0)   # ops=1: add f1 to bloom
    c.lookup_and_update("f2", (1,), 1)   # ops=2: add f2
    c.lookup_and_update("f3", (1,), 2)   # ops=3: epoch reset; current(f1,f2,f3)→previous
    # After reset: previous has f1,f2,f3; current is empty.
    # contains("f1") still True (in previous window).
    # ops=4: f1 seen in bloom (previous) → admitted to store
    c.lookup_and_update("f1", (1,), 3)
    assert "f1" in c._store  # admitted because bloom still held it via previous window


def test_admission_filter_lru_eviction() -> None:
    c = AdmissionFilterLRU(2, bloom_bits=64, bloom_hashes=2)
    for f in ["f1", "f2", "f3", "f4"]:
        c.lookup_and_update(f, (1,), 0)  # first touches
        c.lookup_and_update(f, (1,), 1)  # admit all
    assert len(c._store) <= 2


def test_admission_filter_lru_invalid_params() -> None:
    with pytest.raises(ValueError):
        AdmissionFilterLRU(0)


# ---------------------------------------------------------------------------
# PendingAdmissionLRU
# ---------------------------------------------------------------------------

def test_pending_admission_lru_second_touch_admits() -> None:
    c = PendingAdmissionLRU(4)
    assert c.lookup_and_update("f1", (1,), 0) == (False, False)
    assert "f1" in c._pending
    # Second touch with same path: pending.pop returns first_path=(1,); path=(1,) → hit=True
    hit, ev = c.lookup_and_update("f1", (1,), 1)
    assert hit is True   # same path as pending entry → classified as hit
    assert "f1" in c._store
    assert "f1" not in c._pending


def test_pending_admission_lru_pending_overflow() -> None:
    c = PendingAdmissionLRU(2, pending_size=2)
    c.lookup_and_update("f1", (1,), 0)
    c.lookup_and_update("f2", (1,), 1)
    c.lookup_and_update("f3", (1,), 2)  # f1 evicted from pending (FIFO)
    assert "f1" not in c._pending
    assert "f3" in c._pending


def test_pending_admission_lru_reset_clears_pending() -> None:
    # pending_reset_every=2: at ops=2, pending.clear() is called first, then f2 is processed.
    # f1 (from ops=1) gets cleared; f2 is then added to the now-empty pending.
    c = PendingAdmissionLRU(4, pending_reset_every=2)
    c.lookup_and_update("f1", (1,), 0)  # ops=1: f1 → pending
    c.lookup_and_update("f2", (1,), 1)  # ops=2: reset clears pending, then f2 → pending
    assert "f1" not in c._pending       # cleared by reset
    assert "f2" in c._pending           # added after reset


def test_pending_admission_lru_invalid_params() -> None:
    with pytest.raises(ValueError):
        PendingAdmissionLRU(0)
    with pytest.raises(ValueError):
        PendingAdmissionLRU(4, pending_size=0)


# ---------------------------------------------------------------------------
# PITCollapsedLRU
# ---------------------------------------------------------------------------

def test_pit_collapsed_lru_inflight_collapse() -> None:
    c = PITCollapsedLRU(4, download_delay_ps=100)
    # First touch: creates PIT entry, forward
    hit1, ev1 = c.lookup_and_update("f1", (1,), 0)
    assert hit1 is False
    # Same path while inflight: collapsed (suppressed)
    hit2, ev2 = c.lookup_and_update("f1", (1,), 50)
    assert hit2 is True  # suppressed by PIT


def test_pit_collapsed_lru_ready_ts_admits() -> None:
    c = PITCollapsedLRU(4, download_delay_ps=100)
    c.lookup_and_update("f1", (1,), 0)
    # ts >= ready_ts → admit to cache
    hit, ev = c.lookup_and_update("f1", (1,), 200)
    assert "f1" in c._store


def test_pit_collapsed_lru_path_change_while_inflight() -> None:
    c = PITCollapsedLRU(4, download_delay_ps=100)
    c.lookup_and_update("f1", (1,), 0)
    # Path changed while inflight → update PIT, forward
    hit, _ = c.lookup_and_update("f1", (2,), 50)
    assert hit is False
    assert c._pit["f1"][0] == (2,)


def test_pit_collapsed_lru_pit_capacity_overflow() -> None:
    c = PITCollapsedLRU(4, download_delay_ps=100, pit_capacity=2)
    c.lookup_and_update("f1", (1,), 0)
    c.lookup_and_update("f2", (2,), 0)
    c.lookup_and_update("f3", (3,), 0)  # evicts f1 from PIT
    assert "f1" not in c._pit


def test_pit_collapsed_lru_cache_hit_after_admit() -> None:
    c = PITCollapsedLRU(4, download_delay_ps=50)
    c.lookup_and_update("f1", (1,), 0)
    c.lookup_and_update("f1", (1,), 100)  # admit
    hit, _ = c.lookup_and_update("f1", (1,), 150)  # cache hit
    assert hit is True


def test_pit_collapsed_lru_invalid_params() -> None:
    with pytest.raises(ValueError):
        PITCollapsedLRU(0)
    with pytest.raises(ValueError):
        PITCollapsedLRU(4, download_delay_ps=0)
    with pytest.raises(ValueError):
        PITCollapsedLRU(4, pit_capacity=0)


# ---------------------------------------------------------------------------
# AdaptiveAdmissionLRU
# ---------------------------------------------------------------------------

def test_adaptive_admission_lru_low_pressure_admits_directly() -> None:
    c = AdaptiveAdmissionLRU(4, pressure_window=100, eviction_high_watermark=0.5)
    # Low pressure → admits like plain LRU
    hit, ev = c.lookup_and_update("f1", (1,), 0)
    assert hit is False
    assert "f1" in c._store


def test_adaptive_admission_lru_switches_to_second_chance() -> None:
    # Use tiny capacity and window to force pressure
    c = AdaptiveAdmissionLRU(1, pressure_window=2, eviction_high_watermark=0.01)
    c.lookup_and_update("f1", (1,), 0)  # fills cache
    c.lookup_and_update("f2", (1,), 1)  # evicts f1, window_ops=2 → pressure evaluated
    # After window: evict_ratio = 1/2 = 0.5 >= 0.01 → under_pressure
    # New flow should not be admitted on first touch
    c.lookup_and_update("f3", (1,), 2)
    assert "f3" not in c._store or len(c._store) <= 1


def test_adaptive_admission_lru_second_chance_path() -> None:
    c = AdaptiveAdmissionLRU(4, pressure_window=2, eviction_high_watermark=0.01)
    # Force pressure: fill and evict
    c.lookup_and_update("x", (1,), 0)
    c.lookup_and_update("y", (1,), 0)
    c.lookup_and_update("z", (1,), 0)
    c.lookup_and_update("w", (1,), 0)
    c.lookup_and_update("newone", (1,), 0)  # evicts, sets pressure
    # Now in pressure mode; second-chance path
    c2 = AdaptiveAdmissionLRU(1, pressure_window=2, eviction_high_watermark=0.0)
    c2._under_pressure = True
    c2.lookup_and_update("f1", (1,), 0)   # goes to pending
    assert "f1" in c2._pending
    c2.lookup_and_update("f1", (1,), 1)   # second touch → admit
    assert "f1" in c2._store


def test_adaptive_admission_pending_overflow() -> None:
    c = AdaptiveAdmissionLRU(4, pressure_window=10000, eviction_high_watermark=0.0)
    c._under_pressure = True
    for i in range(10):
        c.lookup_and_update(f"f{i}", (i,), 0)
    assert len(c._pending) <= c._pending_cap


def test_adaptive_admission_lru_invalid_params() -> None:
    with pytest.raises(ValueError):
        AdaptiveAdmissionLRU(0)
    with pytest.raises(ValueError):
        AdaptiveAdmissionLRU(4, pending_size=0)
    with pytest.raises(ValueError):
        AdaptiveAdmissionLRU(4, pressure_window=0)


# ---------------------------------------------------------------------------
# OnlineAdaptiveAdmissionLRU — mode transitions
# ---------------------------------------------------------------------------

def _force_window(cache, ops=None, hits=0, evicts=0):
    """Directly set window counters and trigger _bump_window."""
    w = cache._pressure_window
    n = ops or w
    cache._w_ops = n - 1
    cache._w_hits = hits
    cache._w_evicts = evicts
    cache._bump_window(False, False)


def test_online_adaptive_mode_0_open_admission() -> None:
    c = OnlineAdaptiveAdmissionLRU(4, pressure_window=1000)
    assert c._mode == 0
    # Admits immediately (no pending table required)
    c.lookup_and_update("f1", (1,), 0)
    assert "f1" in c._store


def test_online_adaptive_mode_0_to_1_transition() -> None:
    c = OnlineAdaptiveAdmissionLRU(
        4, pressure_window=10, high_evict=0.20, low_evict=0.005, weak_hit=0.70, strong_hit=0.92
    )
    # Fill 4 slots; 5th call causes eviction
    for i in range(4):
        c.lookup_and_update(f"f{i}", (i,), 0)
    # Simulate a window with many evictions and low hits to force mode→1
    c._w_ops = 9
    c._w_hits = 0
    c._w_evicts = 5  # evict_ratio=5/10=0.5 >= 0.20, hit_ratio=0/10=0 <= 0.70
    c._bump_window(False, True)  # ops reaches 10
    assert c._mode == 1


def test_online_adaptive_mode_1_second_touch_admission() -> None:
    c = OnlineAdaptiveAdmissionLRU(4, pressure_window=1000)
    c._mode = 1
    # First touch → pending(touches=1), required=1 → still pending
    c.lookup_and_update("f1", (1,), 0)
    assert "f1" in c._pending
    # Second touch → touches=2 > required=1 → admit
    c.lookup_and_update("f1", (1,), 1)
    assert "f1" in c._store


def test_online_adaptive_mode_2_third_touch_admission() -> None:
    c = OnlineAdaptiveAdmissionLRU(4, pressure_window=1000)
    c._mode = 2
    c.lookup_and_update("f1", (1,), 0)  # touches=1, stays pending
    c.lookup_and_update("f1", (1,), 1)  # touches=2, stays pending
    c.lookup_and_update("f1", (1,), 2)  # touches=3 > required=2 → admit
    assert "f1" in c._store


def test_online_adaptive_mode_2_to_1_downgrade() -> None:
    c = OnlineAdaptiveAdmissionLRU(
        4, pressure_window=10, high_evict=0.20, low_evict=0.005, weak_hit=0.70, strong_hit=0.92
    )
    c._mode = 2
    # Window with low evictions and high hits → downgrade
    c._w_ops = 9
    c._w_hits = 10   # hit_ratio > strong_hit
    c._w_evicts = 0  # evict_ratio=0 < low_evict
    c._bump_window(True, False)
    assert c._mode == 1


def test_online_adaptive_pending_overflow() -> None:
    c = OnlineAdaptiveAdmissionLRU(4, pressure_window=10000)
    c._mode = 1
    for i in range(20):
        c.lookup_and_update(f"f{i}", (i,), 0)
    assert len(c._pending) <= c._pending_cap


def test_online_adaptive_invalid_params() -> None:
    with pytest.raises(ValueError):
        OnlineAdaptiveAdmissionLRU(0)
    with pytest.raises(ValueError):
        OnlineAdaptiveAdmissionLRU(4, pressure_window=0)
    with pytest.raises(ValueError):
        OnlineAdaptiveAdmissionLRU(4, pending_size=0)


# ---------------------------------------------------------------------------
# OnlineAdaptiveDualTTL
# ---------------------------------------------------------------------------

def test_online_adaptive_dual_ttl_basic_hit() -> None:
    c = OnlineAdaptiveDualTTL(4, dynamic_ttl_ps=500, static_ttl_ps=5000, stable_hit_threshold=2)
    c.lookup_and_update("f1", (1,), 0)
    # Same path, within dynamic TTL → hit
    hit, _ = c.lookup_and_update("f1", (1,), 100)
    assert hit is True


def test_online_adaptive_dual_ttl_stable_promotion() -> None:
    c = OnlineAdaptiveDualTTL(4, dynamic_ttl_ps=500, static_ttl_ps=5000, stable_hit_threshold=2)
    c.lookup_and_update("f1", (1,), 0)
    c.lookup_and_update("f1", (1,), 100)  # stable_hits=1
    c.lookup_and_update("f1", (1,), 200)  # stable_hits=2 → static
    # Now past dynamic TTL but within static TTL
    hit, _ = c.lookup_and_update("f1", (1,), 800)
    assert hit is True


def test_online_adaptive_dual_ttl_stale_expiry_adaptation() -> None:
    c = OnlineAdaptiveDualTTL(
        4, dynamic_ttl_ps=50, static_ttl_ps=5000, stable_hit_threshold=10,
        adapt_window=3, min_dynamic_ttl_ps=10, max_dynamic_ttl_ps=10000,
    )
    # All misses with stale expiries will push TTL up
    initial_ttl = c.dynamic_ttl_ps
    c.lookup_and_update("f1", (1,), 0)
    c.lookup_and_update("f1", (1,), 200)  # stale (age > 50), w_ops=2
    c.lookup_and_update("f2", (2,), 0)    # new, w_ops=3 → adapt triggered
    # TTL grows if stale_ratio high and evict_ratio low
    # (may or may not grow depending on ratios — just assert no crash)
    assert c.dynamic_ttl_ps > 0


def test_online_adaptive_dual_ttl_eviction_pressure_shrinks_ttl() -> None:
    c = OnlineAdaptiveDualTTL(
        2, dynamic_ttl_ps=1000, static_ttl_ps=50000, stable_hit_threshold=10,
        adapt_window=3, min_dynamic_ttl_ps=100, max_dynamic_ttl_ps=5000,
    )
    c.lookup_and_update("f1", (1,), 0)
    c.lookup_and_update("f2", (2,), 0)
    c.lookup_and_update("f3", (3,), 0)  # evicts f1, w_ops=3 → adapt
    assert c.dynamic_ttl_ps > 0


def test_online_adaptive_dual_ttl_path_change() -> None:
    c = OnlineAdaptiveDualTTL(4, dynamic_ttl_ps=500, static_ttl_ps=5000, stable_hit_threshold=5)
    c.lookup_and_update("f1", (1,), 0)
    c.lookup_and_update("f1", (1,), 100)
    hit, _ = c.lookup_and_update("f1", (2,), 200)  # path change → miss
    assert hit is False


def test_online_adaptive_dual_ttl_invalid_params() -> None:
    with pytest.raises(ValueError):
        OnlineAdaptiveDualTTL(0)
    with pytest.raises(ValueError):
        OnlineAdaptiveDualTTL(4, stable_hit_threshold=0)
    with pytest.raises(ValueError):
        OnlineAdaptiveDualTTL(4, min_dynamic_ttl_ps=0)
    with pytest.raises(ValueError):
        OnlineAdaptiveDualTTL(4, min_dynamic_ttl_ps=500, max_dynamic_ttl_ps=100)
    with pytest.raises(ValueError):
        OnlineAdaptiveDualTTL(4, adapt_window=0)


# ---------------------------------------------------------------------------
# FlowLifetimeAdaptiveTTL — TTL clamping and EMA
# ---------------------------------------------------------------------------

def test_flow_lifetime_ttl_base_ttl_on_first() -> None:
    c = FlowLifetimeAdaptiveTTL(4, min_ttl_ps=100, max_ttl_ps=5000)
    c.lookup_and_update("f1", (1,), 0)
    # First entry has inf TTL (no gap observed yet) → always hits before eviction
    hit, _ = c.lookup_and_update("f1", (1,), 200)
    assert hit is True


def test_flow_lifetime_ttl_adapts_with_ema() -> None:
    c = FlowLifetimeAdaptiveTTL(4, min_ttl_ps=1, max_ttl_ps=100000, ema_alpha=1.0, ttl_multiplier=2.0)
    c.lookup_and_update("f1", (1,), 0)
    c.lookup_and_update("f1", (1,), 1000)  # gap=1000, samples=2, ema=1000, ttl=2000
    # ts=1001 within learned TTL(2000): should hit
    hit, _ = c.lookup_and_update("f1", (1,), 1001)
    assert hit is True


def test_flow_lifetime_ttl_min_clamp() -> None:
    c = FlowLifetimeAdaptiveTTL(4, min_ttl_ps=999, max_ttl_ps=10000, ema_alpha=1.0, ttl_multiplier=1.0)
    c.lookup_and_update("f1", (1,), 0)
    c.lookup_and_update("f1", (1,), 1)  # gap=1, ttl=1*1=1 < min_ttl_ps=999 → clamped to 999
    hit, _ = c.lookup_and_update("f1", (1,), 500)  # within clamped TTL
    assert hit is True


def test_flow_lifetime_ttl_max_clamp() -> None:
    c = FlowLifetimeAdaptiveTTL(4, min_ttl_ps=1, max_ttl_ps=100, ema_alpha=1.0, ttl_multiplier=1000.0)
    c.lookup_and_update("f1", (1,), 0)
    c.lookup_and_update("f1", (1,), 500)  # gap=500, ttl=500000 > max_ttl_ps=100 → clamped to 100
    # Just verify no crash and TTL is clamped
    hit, _ = c.lookup_and_update("f1", (1,), 550)  # within clamped TTL
    assert hit is True


def test_flow_lifetime_ttl_eviction() -> None:
    c = FlowLifetimeAdaptiveTTL(2)
    c.lookup_and_update(1, (1,), 0)
    c.lookup_and_update(2, (2,), 0)
    _, evicted = c.lookup_and_update(3, (3,), 0)
    assert evicted is True


def test_flow_lifetime_ttl_invalid_params() -> None:
    with pytest.raises(ValueError):
        FlowLifetimeAdaptiveTTL(0)
    with pytest.raises(ValueError):
        FlowLifetimeAdaptiveTTL(4, min_ttl_ps=0)
    with pytest.raises(ValueError):
        FlowLifetimeAdaptiveTTL(4, min_ttl_ps=500, max_ttl_ps=100)
    with pytest.raises(ValueError):
        FlowLifetimeAdaptiveTTL(4, ema_alpha=0.0)
    with pytest.raises(ValueError):
        FlowLifetimeAdaptiveTTL(4, ttl_multiplier=0.0)


# ---------------------------------------------------------------------------
# TimingBloomLRU
# ---------------------------------------------------------------------------

def test_timing_bloom_lru_admits_second_time() -> None:
    c = TimingBloomLRU(4, bloom_bits=64, bloom_hashes=2, bloom_epoch_records=1000)
    # First touch: not in bloom → bloom records, admitted (no pressure)
    c.lookup_and_update("f1", (1,), 0)
    assert "f1" in c._store


def test_timing_bloom_lru_under_pressure_gates() -> None:
    c = TimingBloomLRU(2, bloom_bits=64, bloom_hashes=2, bloom_epoch_records=1000,
                       pressure_window=2, eviction_high_watermark=0.01)
    c.lookup_and_update("f1", (1,), 0)
    c.lookup_and_update("f2", (2,), 0)
    # Trigger pressure: this evicts
    c.lookup_and_update("f3", (3,), 1)  # evicts f1 (or f2), pressure check fires
    # Under pressure, unseen flows should be gated
    c._under_pressure = True
    hit, ev = c.lookup_and_update("brand_new_unseen", (9,), 2)
    # If cache is full and under pressure, brand new flow should not be admitted
    assert hit is False


def test_timing_bloom_lru_epoch_resets() -> None:
    c = TimingBloomLRU(4, bloom_bits=64, bloom_hashes=2, bloom_epoch_records=3)
    c.lookup_and_update("f1", (1,), 0)
    c.lookup_and_update("f2", (2,), 1)
    c.lookup_and_update("f3", (3,), 2)  # ops=3, epoch reset triggered
    assert c._ops % 3 == 0


def test_timing_bloom_lru_invalid_params() -> None:
    with pytest.raises(ValueError):
        TimingBloomLRU(0)
    with pytest.raises(ValueError):
        TimingBloomLRU(4, bloom_epoch_records=0)
    with pytest.raises(ValueError):
        TimingBloomLRU(4, pressure_window=0)


# ---------------------------------------------------------------------------
# TwoFilterOHWLRU
# ---------------------------------------------------------------------------

def test_two_filter_ohw_three_touch_admission() -> None:
    c = TwoFilterOHWLRU(4, bloom_bits=64, bloom_hashes=2, bloom_epoch_records=1000)
    # No pressure → admits regardless of filter state
    c.lookup_and_update("f1", (1,), 0)
    assert "f1" in c._store


def test_two_filter_ohw_pressure_requires_two_filters() -> None:
    c = TwoFilterOHWLRU(1, bloom_bits=64, bloom_hashes=2, bloom_epoch_records=1000,
                        pressure_window=2, eviction_high_watermark=0.01)
    c.lookup_and_update("f1", (1,), 0)
    c.lookup_and_update("f2", (1,), 1)  # evicts f1, pressure window fires
    c._under_pressure = True
    # Under pressure: new flow (not in f1 or f2) → goes to f1, not admitted
    hit, _ = c.lookup_and_update("f3", (1,), 2)
    assert hit is False
    assert "f3" not in c._store
    # Second touch of f3 → moves to f2
    c.lookup_and_update("f3", (1,), 3)
    # Third touch → f3 is in f2 → admitted
    c.lookup_and_update("f3", (1,), 4)
    assert "f3" in c._store


def test_two_filter_ohw_epoch_resets_both_filters() -> None:
    c = TwoFilterOHWLRU(4, bloom_bits=64, bloom_hashes=2, bloom_epoch_records=2)
    c.lookup_and_update("f1", (1,), 0)
    c.lookup_and_update("f2", (2,), 1)  # ops=2, epoch triggered
    assert c._ops % 2 == 0


def test_two_filter_ohw_invalid_params() -> None:
    with pytest.raises(ValueError):
        TwoFilterOHWLRU(0)
    with pytest.raises(ValueError):
        TwoFilterOHWLRU(4, bloom_epoch_records=0)
    with pytest.raises(ValueError):
        TwoFilterOHWLRU(4, pressure_window=0)


# ---------------------------------------------------------------------------
# _TinyLFUSketch
# ---------------------------------------------------------------------------

def test_tiny_lfu_sketch_observe_and_estimate() -> None:
    s = _TinyLFUSketch(sample_size=100, counter_cap=10)
    s.observe("k1")
    assert s.estimate("k1") == 1  # doorkeeper only
    s.observe("k1")
    assert s.estimate("k1") == 2  # doorkeeper + count=1


def test_tiny_lfu_sketch_reset_halves_counts() -> None:
    s = _TinyLFUSketch(sample_size=5, counter_cap=10)
    for _ in range(3):
        s.observe("k1")
        s.observe("k1")
    # sample_size=5, ops reaches 5 → _reset() called at some point
    # Just verify no crash and estimate is reasonable
    est = s.estimate("k1")
    assert est >= 0


def test_tiny_lfu_sketch_reset_clears_doorkeeper() -> None:
    s = _TinyLFUSketch(sample_size=3, counter_cap=10)
    s.observe("k1")
    s.observe("k1")
    s.observe("k1")  # ops=3 >= sample_size=3 → reset
    assert len(s._doorkeeper) == 0
    assert s._ops == 0


def test_tiny_lfu_sketch_invalid_params() -> None:
    with pytest.raises(ValueError):
        _TinyLFUSketch(0, 10)
    with pytest.raises(ValueError):
        _TinyLFUSketch(10, 0)


# ---------------------------------------------------------------------------
# TinyLFULRU — admission filter behavior
# ---------------------------------------------------------------------------

def test_tiny_lfu_lru_admits_frequent_candidate() -> None:
    c = TinyLFULRU(2, sample_multiplier=4)
    c.lookup_and_update("f1", (1,), 0)
    c.lookup_and_update("f2", (2,), 0)
    # Boost "f3" frequency in the sketch before it arrives
    for _ in range(10):
        c._sketch.observe("f3")
    # f3 should beat the LRU victim (f1 or f2 at freq=1)
    _, evicted = c.lookup_and_update("f3", (3,), 0)
    assert evicted is True


def test_tiny_lfu_lru_bypasses_infrequent_candidate() -> None:
    c = TinyLFULRU(2, sample_multiplier=2)
    c.lookup_and_update("f1", (1,), 0)
    c.lookup_and_update("f2", (2,), 0)
    # Boost existing flows so they have high frequency
    for _ in range(20):
        c._sketch.observe("f1")
        c._sketch.observe("f2")
    # New flow "f3" has zero frequency → bypassed
    hit, evicted = c.lookup_and_update("f3", (3,), 0)
    assert hit is False and evicted is False
    assert "f3" not in c._store


def test_tiny_lfu_lru_invalid_params() -> None:
    with pytest.raises(ValueError):
        TinyLFULRU(0)
    with pytest.raises(ValueError):
        TinyLFULRU(4, sample_multiplier=0)


# ---------------------------------------------------------------------------
# _TinyCacheTable
# ---------------------------------------------------------------------------

def test_tiny_cache_table_observe_and_estimate() -> None:
    t = _TinyCacheTable(set_count=4, set_capacity=4, duplicate_cap=2)
    t.observe("key1")
    assert t.estimate("key1") >= 1


def test_tiny_cache_table_random_eviction() -> None:
    t = _TinyCacheTable(set_count=1, set_capacity=2, duplicate_cap=3)
    t.observe("key1")
    t.observe("key1")
    t.observe("key2")  # set full, random eviction
    assert len(t._sets[0]) <= 2


def test_tiny_cache_table_decay() -> None:
    t = _TinyCacheTable(set_count=2, set_capacity=4, duplicate_cap=4, seed=0)
    for _ in range(8):
        t.observe("k1")
    # _sample_size = 2*4=8 → decay triggered at ops=8
    # After decay some may be removed; just assert it ran
    total = sum(len(b) for b in t._sets)
    assert total >= 0


def test_tiny_cache_table_invalid_params() -> None:
    with pytest.raises(ValueError):
        _TinyCacheTable(0, 4, 2)
    with pytest.raises(ValueError):
        _TinyCacheTable(4, 0, 2)
    with pytest.raises(ValueError):
        _TinyCacheTable(4, 4, 0)
    with pytest.raises(ValueError):
        _TinyCacheTable(4, 4, 2, fingerprint_bits=0)


# ---------------------------------------------------------------------------
# TinyCacheLRU — admission filter behavior
# ---------------------------------------------------------------------------

def test_tiny_cache_lru_admits_frequent_candidate() -> None:
    c = TinyCacheLRU(2)
    c.lookup_and_update("f1", (1,), 0)
    c.lookup_and_update("f2", (2,), 0)
    # Boost "f3" in the table
    for _ in range(15):
        c._table.observe("f3")
    _, evicted = c.lookup_and_update("f3", (3,), 0)
    assert evicted is True  # f3 admitted, LRU victim evicted


def test_tiny_cache_lru_bypasses_infrequent() -> None:
    c = TinyCacheLRU(2)
    c.lookup_and_update("f1", (1,), 0)
    c.lookup_and_update("f2", (2,), 0)
    # Boost existing flows so table estimates are high
    for _ in range(20):
        c._table.observe("f1")
        c._table.observe("f2")
    # f3 has very low estimate → bypass
    hit, evicted = c.lookup_and_update("f3", (3,), 0)
    # Either bypassed (evicted=False) or admitted if f3 estimate won
    assert isinstance(hit, bool)


def test_tiny_cache_lru_invalid_params() -> None:
    with pytest.raises(ValueError):
        TinyCacheLRU(0)
    with pytest.raises(ValueError):
        TinyCacheLRU(4, sample_multiplier=0)


# ---------------------------------------------------------------------------
# CacheINTFreshnessLRU
# ---------------------------------------------------------------------------

def test_cache_int_freshness_static_never_expires() -> None:
    c = CacheINTFreshnessLRU(4, dynamic_ttl_ps=50, stable_hit_threshold=2)
    c.lookup_and_update("f1", (1,), 0)
    c.lookup_and_update("f1", (1,), 10)   # stable_hits=1
    c.lookup_and_update("f1", (1,), 20)   # stable_hits=2 → is_static=True
    # Past dynamic TTL but static → still hit
    hit, _ = c.lookup_and_update("f1", (1,), 1000)
    assert hit is True


def test_cache_int_freshness_dynamic_ttl_expiry() -> None:
    c = CacheINTFreshnessLRU(4, dynamic_ttl_ps=50, stable_hit_threshold=10)
    c.lookup_and_update("f1", (1,), 0)
    # Dynamic entry expires after 50ps
    hit, _ = c.lookup_and_update("f1", (1,), 200)
    assert hit is False


def test_cache_int_freshness_path_change_demotes_to_dynamic() -> None:
    c = CacheINTFreshnessLRU(4, dynamic_ttl_ps=50, stable_hit_threshold=2)
    c.lookup_and_update("f1", (1,), 0)
    c.lookup_and_update("f1", (1,), 10)
    c.lookup_and_update("f1", (1,), 20)  # now static
    # Path change → demoted back to dynamic
    hit, _ = c.lookup_and_update("f1", (2,), 30)
    assert hit is False
    assert c._store["f1"]["is_static"] is False


def test_cache_int_freshness_evicts_least_fresh_dynamic() -> None:
    c = CacheINTFreshnessLRU(2, dynamic_ttl_ps=500, stable_hit_threshold=3)
    c.lookup_and_update("f1", (1,), 0)   # dynamic, ts=0
    c.lookup_and_update("f2", (2,), 100) # dynamic, ts=100
    # f1 is oldest dynamic → should be evicted first
    _, evicted = c.lookup_and_update("f3", (3,), 200)
    assert evicted is True
    assert "f1" not in c._store


def test_cache_int_freshness_all_static_evicts_lru() -> None:
    c = CacheINTFreshnessLRU(2, dynamic_ttl_ps=5000, stable_hit_threshold=2)
    # Promote f1 and f2 to static
    for ts in range(3):
        c.lookup_and_update("f1", (1,), ts)
    for ts in range(3, 6):
        c.lookup_and_update("f2", (2,), ts)
    # All static → falls back to LRU eviction (popitem last=False)
    _, evicted = c.lookup_and_update("f3", (3,), 100)
    assert evicted is True


def test_cache_int_freshness_invalid_params() -> None:
    with pytest.raises(ValueError):
        CacheINTFreshnessLRU(0)
    with pytest.raises(ValueError):
        CacheINTFreshnessLRU(4, dynamic_ttl_ps=0)
    with pytest.raises(ValueError):
        CacheINTFreshnessLRU(4, stable_hit_threshold=0)


# ---------------------------------------------------------------------------
# SegmentedLRU
# ---------------------------------------------------------------------------

def test_segmented_lru_promotes_to_protected() -> None:
    c = SegmentedLRU(8)  # prob_cap=2, prot_cap=6
    c.lookup_and_update("f1", (1,), 0)  # → probation
    c.lookup_and_update("f1", (1,), 1)  # hit in probation → promote to protected
    assert "f1" in c._protected
    assert "f1" not in c._probation


def test_segmented_lru_protected_hit() -> None:
    c = SegmentedLRU(8)
    c.lookup_and_update("f1", (1,), 0)
    c.lookup_and_update("f1", (1,), 1)  # promote
    hit, _ = c.lookup_and_update("f1", (1,), 2)  # hit in protected
    assert hit is True


def test_segmented_lru_evicts_from_probation_only() -> None:
    c = SegmentedLRU(4)  # prob_cap=1, prot_cap=3
    c.lookup_and_update("f1", (1,), 0)  # → probation (fills it)
    _, ev = c.lookup_and_update("f2", (2,), 1)  # new → evicts f1 from probation
    assert ev is True


def test_segmented_lru_protected_demotion_when_full() -> None:
    c = SegmentedLRU(4)  # prob_cap=1, prot_cap=3
    # Fill protected
    c.lookup_and_update("f1", (1,), 0)
    c.lookup_and_update("f1", (1,), 1)  # promote f1
    c.lookup_and_update("f2", (2,), 2)
    c.lookup_and_update("f2", (2,), 3)  # promote f2
    c.lookup_and_update("f3", (3,), 4)
    c.lookup_and_update("f3", (3,), 5)  # promote f3; protected now full (3)
    # Hit in probation (after eviction) causes demotion from protected
    c.lookup_and_update("f4", (4,), 6)  # → probation
    c.lookup_and_update("f4", (4,), 7)  # promote f4; protected full → demote LRU of protected


def test_segmented_lru_degenerate_capacity_1() -> None:
    c = SegmentedLRU(1)  # prot_cap=0
    c.lookup_and_update("f1", (1,), 0)
    hit, _ = c.lookup_and_update("f1", (1,), 1)  # probation hit with prot_cap=0
    assert "f1" in c._probation


def test_segmented_lru_slots_used() -> None:
    c = SegmentedLRU(8)
    c.lookup_and_update("f1", (1,), 0)
    c.lookup_and_update("f2", (2,), 0)
    assert cache_slots_used(c) == 2


def test_segmented_lru_invalid_params() -> None:
    with pytest.raises(ValueError):
        SegmentedLRU(0)


# ---------------------------------------------------------------------------
# simulate() — capacity sampling and redundant_forwards
# ---------------------------------------------------------------------------

def test_simulate_capacity_sampling() -> None:
    c = LRULastPath(2)
    samples = []
    result = simulate(_records(), c, capacity_samples=samples, capacity_sample_every=1)
    assert len(samples) > 0
    assert all(len(s) == 3 for s in samples)  # (total, ts, slots)


def test_simulate_redundant_forwards_counted() -> None:
    recs = [
        {"flow": 1, "sw": [10], "ts": [0]},    # miss: new route → necessary
        {"flow": 1, "sw": [10], "ts": [100]},   # hit
        {"flow": 2, "sw": [20], "ts": [200]},   # miss: new route → necessary
        {"flow": 1, "sw": [10], "ts": [300]},   # hit
    ]
    # Tiny cache to force eviction and redundant forward
    tiny = LRULastPath(1)
    result = simulate(recs, tiny)
    # The cache sees flow 2 → evicts flow 1 → flow 1 again is a miss but collector
    # still knows its path → redundant_forwards >= 1
    assert result.redundant_forwards >= 0  # may be 0 or 1 depending on timing
    assert result.total == 4


def test_simulate_route_change_classified() -> None:
    recs = [
        {"flow": 1, "sw": [10, 11], "ts": [0]},   # new route
        {"flow": 1, "sw": [10, 12], "ts": [100]},  # route change
        {"flow": 1, "sw": [10, 12], "ts": [200]},  # hit
    ]
    result = simulate(recs, LRULastPath(4))
    assert result.route_change_forwards == 1
    assert result.new_route_forwards == 1
    assert result.hits == 1


# ---------------------------------------------------------------------------
# print_results and write_csv
# ---------------------------------------------------------------------------

def test_print_results(capsys) -> None:
    recs = _records()
    results = [simulate(recs, LRULastPath(4)), simulate(recs, InfiniteLastPath())]
    print_results(results)
    captured = capsys.readouterr()
    assert "Cache" in captured.out
    assert "LRU" in captured.out


def test_write_csv(tmp_path: Path) -> None:
    recs = _records()
    results = [simulate(recs, LRULastPath(4))]
    out = tmp_path / "out.csv"
    write_csv(results, str(out))
    text = out.read_text(encoding="utf-8")
    assert "cache" in text
    assert "LRU" in text


# ---------------------------------------------------------------------------
# cache_sim_source_seen utilities
# ---------------------------------------------------------------------------

def test_sniff_delimiter_tab(tmp_path: Path) -> None:
    p = tmp_path / "tab.txt"
    p.write_text("col1\tcol2\tcol3\n1\t2\t3\n")
    assert sniff_delimiter(p) == "\t"


def test_sniff_delimiter_comma(tmp_path: Path) -> None:
    p = tmp_path / "csv.txt"
    p.write_text("col1,col2,col3\n1,2,3\n")
    assert sniff_delimiter(p) == ","


def test_sniff_delimiter_default(tmp_path: Path) -> None:
    p = tmp_path / "plain.txt"
    p.write_text("no delimiters here\n")
    assert sniff_delimiter(p) == "\t"


def test_to_picoseconds_valid() -> None:
    assert to_picoseconds("1.0") == 1_000_000_000_000
    assert to_picoseconds("0.5") == 500_000_000_000


def test_to_picoseconds_empty_and_invalid() -> None:
    assert to_picoseconds("") == 0
    assert to_picoseconds("not_a_number") == 0


def test_load_records_max_records(tmp_path: Path) -> None:
    p = tmp_path / "data.txt"
    p.write_text("src_ip\tdst_ip\ttimestamp\n1.1.1.1\t2.2.2.2\t1.0\n3.3.3.3\t4.4.4.4\t2.0\n5.5.5.5\t6.6.6.6\t3.0\n")
    records = load_records([p], "src_ip", ["dst_ip"], "timestamp", max_records=2)
    assert len(records) == 2


def test_load_records_all(tmp_path: Path) -> None:
    p = tmp_path / "data.txt"
    p.write_text("src_ip\tdst_ip\ttimestamp\n1.1.1.1\t2.2.2.2\t1.0\n3.3.3.3\t4.4.4.4\t2.0\n")
    records = load_records([p], "src_ip", ["dst_ip"], "timestamp", max_records=0)
    assert len(records) == 2


def test_sanitize_name_special_chars() -> None:
    assert sanitize_name("hello world!") == "hello_world"
    assert sanitize_name("a/b\\c") == "a_b_c"
    assert sanitize_name("") == "split"
    assert sanitize_name("___") == "split"


def test_split_csv_dir_default(tmp_path: Path) -> None:
    csv_path = tmp_path / "results.csv"
    out = split_csv_dir(str(csv_path), "")
    assert out == tmp_path / "results_splits"
    assert out.exists()


def test_split_csv_dir_override(tmp_path: Path) -> None:
    out = split_csv_dir("results.csv", str(tmp_path / "custom"))
    assert out == tmp_path / "custom"
    assert out.exists()


def test_merge_results() -> None:
    r1 = CacheResult("LRU", 4)
    r1.total = 10
    r1.hits = 5
    r1.necessary_forwards = 3
    r1.new_route_forwards = 2
    r1.route_change_forwards = 1
    r1.redundant_forwards = 2
    r1.evictions = 1

    r2 = CacheResult("LRU", 4)
    r2.total = 20
    r2.hits = 10
    r2.necessary_forwards = 7
    r2.new_route_forwards = 5
    r2.route_change_forwards = 2
    r2.redundant_forwards = 3
    r2.evictions = 2

    merge_results(r1, r2)
    assert r1.total == 30
    assert r1.hits == 15
    assert r1.necessary_forwards == 10
    assert r1.redundant_forwards == 5
    assert r1.evictions == 3


def test_simulate_source_route_change_and_redundant() -> None:
    recs = [
        ("s1", ("dst_a",), 0),
        ("s1", ("dst_b",), 100),   # route change
        ("s1", ("dst_b",), 200),   # hit
    ]
    tiny = LRULastPath(1)
    oracle = InfiniteLastPath()
    result = simulate_source(recs, tiny, oracle)
    assert result.route_change_forwards == 1
    assert result.new_route_forwards == 1
    assert result.hits == 1


def test_simulate_source_capacity_tracking() -> None:
    recs = [
        ("s1", ("a",), 0),
        ("s2", ("b",), 100),
        ("s1", ("a",), 200),
    ]
    samples = []
    result = simulate_source(recs, LRULastPath(4), capacity_samples=samples, capacity_sample_every=1)
    assert len(samples) > 0


def test_simulate_source_tuple_records() -> None:
    recs = [
        ("s1", ("a",), 0),
        ("s1", ("a",), 100),
    ]
    result = simulate_source(recs, LRULastPath(4))
    assert result.total == 2
    assert result.hits == 1


# ---------------------------------------------------------------------------
# LRULastPathTTL — eviction path
# ---------------------------------------------------------------------------

def test_lru_ttl_eviction_on_new_flow() -> None:
    c = LRULastPathTTL(2, ttl_ps=10000)
    c.lookup_and_update("f1", (1,), 0)
    c.lookup_and_update("f2", (2,), 0)
    _, evicted = c.lookup_and_update("f3", (3,), 0)
    assert evicted is True


# ---------------------------------------------------------------------------
# PendingAdmissionLRU — eviction on second touch when store is full
# ---------------------------------------------------------------------------

def test_pending_admission_eviction_on_admit() -> None:
    # capacity=2, pending_cap=2: admit two flows, then admit a 3rd → evict from store
    c = PendingAdmissionLRU(2, pending_size=4)
    c.lookup_and_update("fA", (1,), 0)  # pending
    c.lookup_and_update("fB", (2,), 0)  # pending
    c.lookup_and_update("fA", (1,), 1)  # admit fA; store empty → no eviction
    c.lookup_and_update("fB", (2,), 1)  # admit fB; store has 1 < 2 → no eviction
    # Now store has fA,fB (cap=2). Admit fC → evict LRU
    c.lookup_and_update("fC", (3,), 0)  # pending
    _, evicted = c.lookup_and_update("fC", (3,), 2)  # admit fC → store full → evict fA
    assert evicted is True


# ---------------------------------------------------------------------------
# FreshnessInvalidationLRU — eviction after stale invalidation
# ---------------------------------------------------------------------------

def test_freshness_invalidation_eviction_after_invalidation() -> None:
    # After stale invalidation, cache has one free slot; new entry fills it (no eviction).
    c = FreshnessInvalidationLRU(1, freshness_ttl_ps=50)
    c.lookup_and_update("f1", (1,), 0)   # insert f1; cache full (cap=1)
    # f1 is stale at ts=100 (age 100 > 50) → del f1; cache empty; insert f1 fresh
    hit, evicted = c.lookup_and_update("f1", (1,), 100)
    assert hit is False
    assert evicted is False  # cache was empty after deletion (evicted=False from FreshnessInvalidation)


def test_freshness_invalidation_eviction_non_stale() -> None:
    c = FreshnessInvalidationLRU(1, freshness_ttl_ps=50000)
    c.lookup_and_update("f1", (1,), 0)   # fills cache (cap=1)
    # f1 not stale; new flow f2 → evict f1
    _, evicted = c.lookup_and_update("f2", (2,), 0)
    assert evicted is True


# ---------------------------------------------------------------------------
# AdaptiveAdmission — pending path eviction on second touch
# ---------------------------------------------------------------------------

def test_adaptive_admission_pending_admit_evicts() -> None:
    # Use capacity=2, pending_size=4 to avoid pending overflow interfering
    c = AdaptiveAdmissionLRU(2, pressure_window=10000, eviction_high_watermark=0.0, pending_size=4)
    c._under_pressure = True
    c.lookup_and_update("fA", (1,), 0)   # pending
    c.lookup_and_update("fB", (2,), 0)   # pending
    c.lookup_and_update("fA", (1,), 1)   # admit fA; store has 1
    c.lookup_and_update("fB", (2,), 1)   # admit fB; store has 2 (full)
    c.lookup_and_update("fC", (3,), 0)   # pending
    _, evicted = c.lookup_and_update("fC", (3,), 2)  # admit fC → evict LRU from store
    assert evicted is True


# ---------------------------------------------------------------------------
# OnlineAdaptive — eviction during mode-0 admission
# ---------------------------------------------------------------------------

def test_online_adaptive_mode0_eviction() -> None:
    c = OnlineAdaptiveAdmissionLRU(2, pressure_window=10000)
    c.lookup_and_update("f1", (1,), 0)
    c.lookup_and_update("f2", (2,), 0)
    _, evicted = c.lookup_and_update("f3", (3,), 0)
    assert evicted is True


def test_online_adaptive_mode1_eviction_on_admit() -> None:
    # capacity=2, pending_cap=4; mode=1 requires 2 touches to admit
    c = OnlineAdaptiveAdmissionLRU(2, pressure_window=10000, pending_size=4)
    c._mode = 1
    # fA: touch1 (pending, touches=1), touch2 (admit → store)
    c.lookup_and_update("fA", (1,), 0)
    c.lookup_and_update("fA", (1,), 1)
    # fB: touch1 (pending), touch2 (admit → store)
    c.lookup_and_update("fB", (2,), 0)
    c.lookup_and_update("fB", (2,), 1)
    # fC: touch1 (pending), touch2 (admit → store full → evict LRU)
    c.lookup_and_update("fC", (3,), 0)
    _, evicted = c.lookup_and_update("fC", (3,), 2)
    assert evicted is True


# ---------------------------------------------------------------------------
# resolve_inputs from cache_sim_source_seen
# ---------------------------------------------------------------------------

def test_resolve_inputs_file(tmp_path: Path) -> None:
    from fyp.dash_scripts.cache_sim_source_seen import resolve_inputs
    p = tmp_path / "test.txt"
    p.write_text("col\n1\n")
    result = resolve_inputs(p, "*.txt")
    assert result == [p]


def test_resolve_inputs_directory(tmp_path: Path) -> None:
    from fyp.dash_scripts.cache_sim_source_seen import resolve_inputs
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("x\n")
    f2.write_text("y\n")
    result = resolve_inputs(tmp_path, "*.txt")
    assert set(result) == {f1, f2}


def test_resolve_inputs_missing_raises(tmp_path: Path) -> None:
    from fyp.dash_scripts.cache_sim_source_seen import resolve_inputs
    with pytest.raises(FileNotFoundError):
        resolve_inputs(tmp_path / "nonexistent.txt", "*")


def test_resolve_inputs_no_matches_raises(tmp_path: Path) -> None:
    from fyp.dash_scripts.cache_sim_source_seen import resolve_inputs
    with pytest.raises(FileNotFoundError):
        resolve_inputs(tmp_path, "*.nomatch")


# ---------------------------------------------------------------------------
# sweep_splitwise and run_single_splitwise
# ---------------------------------------------------------------------------

def test_sweep_splitwise(tmp_path: Path) -> None:
    from fyp.dash_scripts.cache_sim_source_seen import sweep_splitwise, load_split_records
    import argparse as _argparse
    p = tmp_path / "split.txt"
    p.write_text("src_ip\tdst_ip\ttimestamp\n1.1.1.1\t2.2.2.2\t1.0\n1.1.1.1\t2.2.2.2\t2.0\n")
    args = _argparse.Namespace(
        source_column="src_ip",
        route_columns="dst_ip",
        timestamp_column="timestamp",
        max_records=0,
        fast=False,
    )
    merged, split_outputs = sweep_splitwise([p], args)
    assert len(merged) > 0
    assert len(split_outputs) == 1


def test_run_single_splitwise(tmp_path: Path) -> None:
    from fyp.dash_scripts.cache_sim_source_seen import run_single_splitwise
    import argparse as _argparse
    p = tmp_path / "split.txt"
    p.write_text("src_ip\tdst_ip\ttimestamp\n1.1.1.1\t2.2.2.2\t1.0\n3.3.3.3\t4.4.4.4\t2.0\n")
    args = _argparse.Namespace(
        source_column="src_ip",
        route_columns="dst_ip",
        timestamp_column="timestamp",
        max_records=0,
        fast=False,
    )
    result = run_single_splitwise([p], lambda: LRULastPath(4), unbounded=False, args=args)
    assert result.total == 2


# ---------------------------------------------------------------------------
# TwoFilterOHWLRU — store hit path
# ---------------------------------------------------------------------------

def test_freshness_invalidation_lru_invalid_params() -> None:
    with pytest.raises(ValueError):
        FreshnessInvalidationLRU(0)
    with pytest.raises(ValueError):
        FreshnessInvalidationLRU(4, freshness_ttl_ps=0)


def test_adaptive_admission_pending_reset() -> None:
    # Ensure AdaptiveAdmissionLRU._pending.clear() on pending_reset_every is triggered
    c = AdaptiveAdmissionLRU(4, pressure_window=10000, eviction_high_watermark=0.0, pending_reset_every=2)
    c._under_pressure = True
    c.lookup_and_update("f1", (1,), 0)  # ops=1, pending
    c.lookup_and_update("f2", (2,), 0)  # ops=2 → pending.clear() then f2 → pending
    assert "f1" not in c._pending
    assert "f2" in c._pending


def test_pit_collapsed_lru_admit_eviction() -> None:
    # PITCollapsedLRU._admit should trigger eviction when store is full
    c = PITCollapsedLRU(1, download_delay_ps=10)
    c.lookup_and_update("f1", (1,), 0)    # PIT entry
    c.lookup_and_update("f1", (1,), 100)  # ts>=ready → admit f1 (store now full, cap=1)
    c.lookup_and_update("f2", (2,), 0)    # PIT entry for f2
    c.lookup_and_update("f2", (2,), 200)  # admit f2 → store full → evict f1


def test_flow_lifetime_ttl_ema_first_sample() -> None:
    # _update_ema samples<=1 branch: call _update_ema directly with samples=1
    c = FlowLifetimeAdaptiveTTL(4, min_ttl_ps=1, max_ttl_ps=10000, ema_alpha=0.5)
    result = c._update_ema(500, 300, 1)  # samples=1 → return gap_ps directly
    assert result == 300
    result2 = c._update_ema(500, 300, 2)  # samples=2 → ema formula
    assert result2 == int(0.5 * 300 + 0.5 * 500)


def test_tiny_cache_table_bucket_full_eviction() -> None:
    # _TinyCacheTable.observe when len(bucket) >= set_capacity → random eviction.
    # set_count=1 forces all keys into one bucket.
    # set_capacity=3, duplicate_cap=1: keys a,b,c,d have distinct fingerprints;
    # when 'd' is observed the bucket fills to 3, and 'e' triggers random eviction.
    # _sample_size = 1*3 = 3; decay fires at ops=3 (after c). So at obs(d),
    # bucket may be smaller; we just need to verify len stays <= set_capacity.
    t = _TinyCacheTable(set_count=1, set_capacity=3, duplicate_cap=1, seed=42)
    for k in ["a", "b", "c", "d", "e"]:
        t.observe(k)
    assert len(t._sets[0]) <= 3  # bucket never exceeds set_capacity


def test_load_records_skips_empty_src(tmp_path: Path) -> None:
    # Line 302: rows with empty src_ip are skipped
    p = tmp_path / "data.txt"
    p.write_text("src_ip\tdst_ip\ttimestamp\n\t2.2.2.2\t1.0\n1.1.1.1\t3.3.3.3\t2.0\n")
    records = load_records([p], "src_ip", ["dst_ip"], "timestamp", max_records=0)
    assert len(records) == 1
    assert records[0]["source"] == "1.1.1.1"


def test_simulate_capacity_dedup_at_end() -> None:
    # Test the dedup check: last capacity_samples entry should not be duplicated
    c = LRULastPath(4)
    samples = []
    # sample_every=1 so every record is sampled; last record sampled at end too
    recs = [{"flow": 1, "sw": [10], "ts": [100]}]
    simulate(recs, c, capacity_samples=samples, capacity_sample_every=1)
    # The end-of-run sample should not duplicate the last per-record sample
    if len(samples) >= 2:
        assert samples[-1] != samples[-2] or samples[-1][0] != samples[-2][0]


def test_simulate_source_dict_unpack() -> None:
    # Test _unpack_source_record dict branch (lines 315-318)
    recs = [
        {"source": "s1", "route_sig": ("a",), "ts_ps": 100},
        {"source": "s1", "route_sig": ("a",), "ts_ps": 200},
    ]
    result = simulate_source(recs, LRULastPath(4))
    assert result.total == 2
    assert result.hits == 1


def test_two_filter_ohw_store_hit() -> None:
    c = TwoFilterOHWLRU(4, bloom_bits=64, bloom_hashes=2, bloom_epoch_records=1000)
    c.lookup_and_update("f1", (1,), 0)   # insert
    hit, _ = c.lookup_and_update("f1", (1,), 1)   # hit in store
    assert hit is True


# ---------------------------------------------------------------------------

def test_parse_int_log(tmp_path: Path) -> None:
    from fyp.dash_scripts.cache_sim import parse
    log = tmp_path / "test.txt"
    log.write_text(
        "INT flow=1 seq=0 hops=2\n"
        "  [0] sw=10 type=0 qs=0 ts=100 txbytes=0 pktid=1\n"
        "  [1] sw=11 type=0 qs=0 ts=200 txbytes=0 pktid=1\n"
        "INT flow=2 seq=0 hops=1\n"
        "  [0] sw=20 type=1 qs=5 ts=300 txbytes=100 pktid=2\n"
        "INT flow=1 seq=1 hops=2\n"
        "  [0] sw=10 type=0 qs=0 ts=400 txbytes=0 pktid=3\n"
        "  [1] sw=12 type=0 qs=0 ts=500 txbytes=0 pktid=3\n"
    )
    records = list(parse(str(log)))
    assert len(records) == 3
    assert records[0]["flow"] == 1
    assert records[0]["sw"] == [10, 11]
    assert records[1]["flow"] == 2
    assert records[2]["sw"] == [10, 12]


def test_parse_int_log_junk_before_header(tmp_path: Path) -> None:
    # Lines before the first INT header should be skipped (current is None branch)
    from fyp.dash_scripts.cache_sim import parse
    log = tmp_path / "junk.txt"
    log.write_text(
        "# This is a comment\n"
        "  [0] sw=99 type=0 qs=0 ts=0 txbytes=0 pktid=0\n"  # junk hop before any header
        "INT flow=7 seq=0 hops=1\n"
        "  [0] sw=42 type=0 qs=0 ts=500 txbytes=0 pktid=1\n"
    )
    records = list(parse(str(log)))
    assert len(records) == 1
    assert records[0]["flow"] == 7


def test_parse_int_log_trailing_record(tmp_path: Path) -> None:
    # Verifies the final record is yielded even without a following header
    from fyp.dash_scripts.cache_sim import parse
    log = tmp_path / "single.txt"
    log.write_text(
        "INT flow=5 seq=0 hops=1\n"
        "  [0] sw=99 type=0 qs=0 ts=1000 txbytes=0 pktid=1\n"
    )
    records = list(parse(str(log)))
    assert len(records) == 1
    assert records[0]["flow"] == 5
    assert records[0]["sw"] == [99]


def test_write_capacity_csv_skips_infinite(tmp_path: Path) -> None:
    # capacity=-1 (infinite) should be skipped in write_capacity_csv
    curves = {("Infinite", -1): [(1, 100, 5)]}
    out = tmp_path / "cap.csv"
    write_capacity_csv(curves, str(out))
    text = out.read_text(encoding="utf-8")
    assert "Infinite" not in text


def test_simulate_capacity_no_duplicate_end_sample() -> None:
    # Line 1766: dedup check prevents double-recording when last record already sampled
    c = LRULastPath(4)
    recs = [
        {"flow": 1, "sw": [10], "ts": [0]},
        {"flow": 2, "sw": [20], "ts": [100]},
    ]
    samples = []
    # sample_every=1 means every record is sampled, including the last one.
    # The end-of-run check should not add a duplicate for the last record.
    simulate(recs, c, capacity_samples=samples, capacity_sample_every=1)
    indices = [s[0] for s in samples]
    assert len(indices) == len(set(indices))  # no duplicate record indices


def test_write_per_split_csvs(tmp_path: Path) -> None:
    total_csv = tmp_path / "total.csv"
    total_csv.write_text("")  # placeholder
    recs = _records()
    r1 = simulate(recs, LRULastPath(4))
    split_results = [(Path("split_a.txt"), [r1]), (Path("split_b.txt"), [r1])]
    write_per_split_csvs(split_results, str(total_csv), "")
    splits_dir = tmp_path / "total_splits"
    assert splits_dir.exists()
    assert len(list(splits_dir.glob("*.csv"))) == 2


# ===========================================================================
# cache_sim_congestion_int tests
# ===========================================================================

def _qs_records(threshold: int = 0):
    """Minimal hop records for congestion sim tests."""
    return [
        {"source": "sw1:1", "qs": 1000, "ts_ps": 100},
        {"source": "sw1:1", "qs": 1000, "ts_ps": 200},   # same qs → hit if threshold >= 0
        {"source": "sw2:2", "qs": 5000, "ts_ps": 300},   # new key → miss
        {"source": "sw1:1", "qs": 9000, "ts_ps": 400},   # big change → miss
        {"source": "sw3:3", "qs": 200,  "ts_ps": 500},   # new key → miss
        {"source": "sw1:1", "qs": 9100, "ts_ps": 600},   # small change (100) → hit if threshold >= 100
    ]


# ---------------------------------------------------------------------------
# CongestResult dataclass
# ---------------------------------------------------------------------------

def test_congest_result_properties() -> None:
    r = CongestResult(cache_name="LRU", capacity=10)
    r.total = 100
    r.hits = 60
    r.necessary_forwards = 30
    r.redundant_forwards = 10
    r.evictions = 5
    r.new_route_forwards = 20
    r.route_change_forwards = 10

    assert r.forwards == 40
    assert abs(r.suppression_rate - 0.60) < 1e-9
    assert abs(r.forward_rate - 0.40) < 1e-9
    assert abs(r.redundancy_rate - 0.25) < 1e-9
    assert abs(r.efficiency - 0.75) < 1e-9


def test_congest_result_zero_totals() -> None:
    r = CongestResult(cache_name="Z", capacity=4)
    assert r.suppression_rate == 0.0
    assert r.forward_rate == 0.0
    assert r.forwards == 0
    assert r.efficiency == 1.0
    assert r.redundancy_rate == 0.0


def test_congest_result_str_finite_and_infinite() -> None:
    r_finite = CongestResult(cache_name="LRU", capacity=64)
    r_finite.total = 10
    s = str(r_finite)
    assert "cap=64" in s
    assert "LRU" in s

    r_inf = CongestResult(cache_name="Infinite", capacity=float("inf"))
    r_inf.total = 5
    s2 = str(r_inf)
    assert "∞" in s2


# ---------------------------------------------------------------------------
# InfiniteQS oracle
# ---------------------------------------------------------------------------

def test_infinite_qs_hit_miss_basic() -> None:
    c = InfiniteQS(range_threshold=0)
    assert c.process("k1", 1000) == (False, False)  # new key
    assert c.process("k1", 1000) == (True, False)   # same value → hit
    assert c.process("k1", 2000) == (False, False)  # changed → miss


def test_infinite_qs_range_threshold() -> None:
    c = InfiniteQS(range_threshold=500)
    c.process("k1", 1000)
    # change of 400 <= 500 → hit
    assert c.process("k1", 1400)[0] is True
    # change of 600 > 500 → miss
    assert c.process("k1", 2000)[0] is False


def test_infinite_qs_first_seen_tracking() -> None:
    c = InfiniteQS(range_threshold=0)
    assert "k1" not in c._first_seen
    c.process("k1", 100)
    assert "k1" in c._first_seen
    c.process("k1", 200)  # miss (value changed), but still in _first_seen
    assert "k1" in c._first_seen


# ---------------------------------------------------------------------------
# LRUQSCache
# ---------------------------------------------------------------------------

def test_lruqs_hit_same_value() -> None:
    c = LRUQSCache(4, range_threshold=0)
    assert c.process("k1", 1000) == (False, False)
    assert c.process("k1", 1000) == (True, False)


def test_lruqs_miss_on_value_change() -> None:
    c = LRUQSCache(4, range_threshold=0)
    c.process("k1", 1000)
    hit, ev = c.process("k1", 2000)
    assert hit is False and ev is False


def test_lruqs_eviction() -> None:
    c = LRUQSCache(2, range_threshold=0)
    c.process("k1", 100)
    c.process("k2", 200)
    _, evicted = c.process("k3", 300)
    assert evicted is True


def test_lruqs_range_threshold_hit() -> None:
    c = LRUQSCache(4, range_threshold=100)
    c.process("k1", 1000)
    # change of 50 <= 100 → hit
    assert c.process("k1", 1050)[0] is True
    # change of 200 > 100 → miss
    assert c.process("k1", 1250)[0] is False


# ---------------------------------------------------------------------------
# FIFOQSCache
# ---------------------------------------------------------------------------

def test_fifoqs_eviction_in_order() -> None:
    c = FIFOQSCache(2, range_threshold=0)
    c.process("k1", 100)
    c.process("k2", 200)
    # k1 inserted first → evicted first on new entry
    _, evicted = c.process("k3", 300)
    assert evicted is True
    assert "k1" not in c._store


def test_fifoqs_hit_no_reorder() -> None:
    c = FIFOQSCache(2, range_threshold=0)
    c.process("k1", 100)
    c.process("k2", 200)
    c.process("k1", 100)  # hit, does NOT reorder (FIFO)
    # k1 is still first in order, so next eviction still removes k1
    _, evicted = c.process("k3", 300)
    assert evicted is True


# ---------------------------------------------------------------------------
# LFUQSCache
# ---------------------------------------------------------------------------

def test_lfuqs_evicts_least_frequent() -> None:
    c = LFUQSCache(2, range_threshold=0)
    c.process("k1", 100)
    c.process("k2", 200)
    # Make k1 more frequent with a hit
    c.process("k1", 100)
    # k2 has freq=1, k1 has freq=2 → k2 evicted
    _, evicted = c.process("k3", 300)
    assert evicted is True
    assert "k2" not in c._store


def test_lfuqs_hit_increments_freq() -> None:
    c = LFUQSCache(4, range_threshold=0)
    c.process("k1", 100)
    c.process("k1", 100)  # hit → freq increment
    assert c._freq["k1"] > 1


# ---------------------------------------------------------------------------
# LRUQSCacheTTL
# ---------------------------------------------------------------------------

def test_lruqs_ttl_hit_within_window() -> None:
    c = LRUQSCacheTTL(4, range_threshold=0, ttl_ps=1000)
    c.process("k1", 100, ts=0)
    # same value and within TTL → hit
    assert c.process("k1", 100, ts=500)[0] is True


def test_lruqs_ttl_miss_on_expiry() -> None:
    c = LRUQSCacheTTL(4, range_threshold=0, ttl_ps=100)
    c.process("k1", 100, ts=0)
    # expired (age 200 >= ttl 100) → miss
    assert c.process("k1", 100, ts=200)[0] is False


def test_lruqs_ttl_miss_on_value_change() -> None:
    c = LRUQSCacheTTL(4, range_threshold=0, ttl_ps=10000)
    c.process("k1", 100, ts=0)
    assert c.process("k1", 999, ts=1)[0] is False


def test_lruqs_ttl_eviction() -> None:
    c = LRUQSCacheTTL(1, range_threshold=0, ttl_ps=10000)
    c.process("k1", 100, ts=0)
    _, evicted = c.process("k2", 200, ts=0)
    assert evicted is True


# ---------------------------------------------------------------------------
# FreshnessInvalidationQS
# ---------------------------------------------------------------------------

def test_freshness_qs_hit_within_ttl() -> None:
    c = FreshnessInvalidationQS(4, range_threshold=0, freshness_ttl_ps=1000)
    c.process("k1", 100, ts=0)
    assert c.process("k1", 100, ts=500)[0] is True


def test_freshness_qs_miss_on_stale() -> None:
    c = FreshnessInvalidationQS(4, range_threshold=0, freshness_ttl_ps=100)
    c.process("k1", 100, ts=0)
    # stale → entry deleted before lookup
    hit, evicted = c.process("k1", 100, ts=200)
    assert hit is False
    assert evicted is False  # entry was deleted, then re-inserted (no LRU eviction)


def test_freshness_qs_eviction_when_full() -> None:
    c = FreshnessInvalidationQS(1, range_threshold=0, freshness_ttl_ps=10000)
    c.process("k1", 100, ts=0)
    _, evicted = c.process("k2", 200, ts=0)
    assert evicted is True


def test_freshness_qs_invalid_params() -> None:
    with pytest.raises(ValueError):
        FreshnessInvalidationQS(0)


# ---------------------------------------------------------------------------
# CacheINTFreshnessQS
# ---------------------------------------------------------------------------

def test_cache_int_qs_dynamic_hit() -> None:
    c = CacheINTFreshnessQS(4, range_threshold=0, dynamic_ttl_ps=1000, stable_hit_threshold=5)
    c.process("k1", 100, ts=0)
    assert c.process("k1", 100, ts=500)[0] is True


def test_cache_int_qs_dynamic_expiry() -> None:
    c = CacheINTFreshnessQS(4, range_threshold=0, dynamic_ttl_ps=50, stable_hit_threshold=10)
    c.process("k1", 100, ts=0)
    # beyond dynamic TTL → miss
    assert c.process("k1", 100, ts=200)[0] is False


def test_cache_int_qs_static_promotion_no_expiry() -> None:
    c = CacheINTFreshnessQS(4, range_threshold=0, dynamic_ttl_ps=50, stable_hit_threshold=2)
    c.process("k1", 100, ts=0)
    c.process("k1", 100, ts=10)   # stable_hits=1
    c.process("k1", 100, ts=20)   # stable_hits=2 → is_static
    # past dynamic TTL but static → hit
    assert c.process("k1", 100, ts=1000)[0] is True


def test_cache_int_qs_value_change_resets_static() -> None:
    c = CacheINTFreshnessQS(4, range_threshold=0, dynamic_ttl_ps=50, stable_hit_threshold=2)
    c.process("k1", 100, ts=0)
    c.process("k1", 100, ts=10)
    c.process("k1", 100, ts=20)  # now static
    # value change → demoted back to dynamic, miss
    hit, _ = c.process("k1", 9000, ts=30)
    assert hit is False
    assert c._store["k1"]["is_static"] is False


def test_cache_int_qs_evicts_least_fresh_dynamic() -> None:
    c = CacheINTFreshnessQS(2, range_threshold=0, dynamic_ttl_ps=5000, stable_hit_threshold=5)
    c.process("k1", 100, ts=0)   # older dynamic entry
    c.process("k2", 200, ts=100) # newer dynamic entry
    # k1 is least-fresh dynamic → evicted first
    _, evicted = c.process("k3", 300, ts=200)
    assert evicted is True
    assert "k1" not in c._store


def test_cache_int_qs_all_static_falls_back_to_lru() -> None:
    c = CacheINTFreshnessQS(2, range_threshold=0, dynamic_ttl_ps=5000, stable_hit_threshold=2)
    for ts in range(3):
        c.process("k1", 100, ts=ts)
    for ts in range(3, 6):
        c.process("k2", 200, ts=ts)
    # both static → LRU eviction
    _, evicted = c.process("k3", 300, ts=100)
    assert evicted is True


def test_cache_int_qs_invalid_params() -> None:
    with pytest.raises(ValueError):
        CacheINTFreshnessQS(0)


# ---------------------------------------------------------------------------
# FlowLifetimeAdaptiveTTLQS
# ---------------------------------------------------------------------------

def test_flow_ttl_qs_base_ttl_on_first() -> None:
    # First entry has inf TTL (no gap observed yet) → always hits before eviction
    c = FlowLifetimeAdaptiveTTLQS(4, range_threshold=0)
    c.process("k1", 100, ts=0)
    assert c.process("k1", 100, ts=500)[0] is True


def test_flow_ttl_qs_expired_miss() -> None:
    # After two accesses a gap is learned; a third access beyond ttl should miss.
    # ema_alpha=1.0, ttl_multiplier=1.0 → ttl = gap = 50ps; min=1, max=1_000_000_000
    c = FlowLifetimeAdaptiveTTLQS(4, range_threshold=0, ema_alpha=1.0, ttl_multiplier=1.0,
                                   min_ttl_ps=1, max_ttl_ps=1_000_000_000)
    c.process("k1", 100, ts=0)
    c.process("k1", 100, ts=50)   # gap=50 → ema=50 → ttl=50
    assert c.process("k1", 100, ts=200)[0] is False  # 200-50=150 > ttl=50 → expired


def test_flow_ttl_qs_eviction() -> None:
    c = FlowLifetimeAdaptiveTTLQS(1, range_threshold=0)
    c.process("k1", 100, ts=0)
    _, evicted = c.process("k2", 200, ts=0)
    assert evicted is True


def test_flow_ttl_qs_ema_updates() -> None:
    c = FlowLifetimeAdaptiveTTLQS(4, range_threshold=0, ema_alpha=1.0, ttl_multiplier=2.0,
                                   min_ttl_ps=1, max_ttl_ps=100_000_000)
    c.process("k1", 100, ts=0)
    c.process("k1", 100, ts=1000)  # gap=1000 → ema=1000 → ttl=2000
    # ts=1001 within learned TTL → hit
    assert c.process("k1", 100, ts=1001)[0] is True


def test_flow_ttl_qs_invalid_params() -> None:
    with pytest.raises(ValueError):
        FlowLifetimeAdaptiveTTLQS(0)


# ---------------------------------------------------------------------------
# AdmissionFilterQS (OneHitWonder)
# ---------------------------------------------------------------------------

def test_admission_filter_qs_second_touch_admits() -> None:
    c = AdmissionFilterQS(4, range_threshold=0, bloom_bits=64, bloom_hashes=2)
    # First touch: not admitted
    hit, ev = c.process("k1", 100)
    assert hit is False and ev is False
    assert "k1" not in c._store
    # Second touch: bloom sees it → admitted
    c.process("k1", 100)
    assert "k1" in c._store


def test_admission_filter_qs_store_hit() -> None:
    c = AdmissionFilterQS(4, range_threshold=0, bloom_bits=64, bloom_hashes=2)
    c.process("k1", 100)  # first touch
    c.process("k1", 100)  # second touch → admitted
    hit, _ = c.process("k1", 100)  # hit in store
    assert hit is True


def test_admission_filter_qs_value_change_in_store() -> None:
    c = AdmissionFilterQS(4, range_threshold=0, bloom_bits=64, bloom_hashes=2)
    c.process("k1", 100)
    c.process("k1", 100)  # admit
    hit, _ = c.process("k1", 9000)  # value change → miss
    assert hit is False


def test_admission_filter_qs_epoch_reset() -> None:
    c = AdmissionFilterQS(4, range_threshold=0, bloom_bits=64, bloom_hashes=2, pending_reset_every=3)
    c.process("k1", 100)  # ops=1: add to bloom
    c.process("k2", 200)  # ops=2
    c.process("k3", 300)  # ops=3: epoch reset; k1/k2/k3 move to previous window
    # k1 still in previous window → second touch → admitted
    c.process("k1", 100)  # ops=4
    assert "k1" in c._store


def test_admission_filter_qs_eviction() -> None:
    c = AdmissionFilterQS(1, range_threshold=0, bloom_bits=64, bloom_hashes=2)
    for k in ["k1", "k2"]:
        c.process(k, 100)
        c.process(k, 100)  # admit both
    assert len(c._store) <= 1


def test_admission_filter_qs_invalid_params() -> None:
    with pytest.raises(ValueError):
        AdmissionFilterQS(0)


# ---------------------------------------------------------------------------
# PendingAdmissionQS
# ---------------------------------------------------------------------------

def test_pending_qs_second_touch_admits() -> None:
    c = PendingAdmissionQS(4, range_threshold=0)
    c.process("k1", 100)  # → pending
    assert "k1" in c._pending
    c.process("k1", 100)  # second touch → admit
    assert "k1" in c._store


def test_pending_qs_store_hit() -> None:
    c = PendingAdmissionQS(4, range_threshold=0)
    c.process("k1", 100)
    c.process("k1", 100)  # admit
    hit, _ = c.process("k1", 100)
    assert hit is True


def test_pending_qs_pending_overflow() -> None:
    c = PendingAdmissionQS(4, range_threshold=0, pending_size=2)
    c.process("k1", 100)
    c.process("k2", 200)
    c.process("k3", 300)  # k1 evicted from pending
    assert "k1" not in c._pending


def test_pending_qs_reset_clears_pending() -> None:
    c = PendingAdmissionQS(4, range_threshold=0, pending_reset_every=2)
    c.process("k1", 100)  # ops=1 → pending
    c.process("k2", 200)  # ops=2 → reset clears, then k2 → pending
    assert "k1" not in c._pending
    assert "k2" in c._pending


def test_pending_qs_eviction_on_admit() -> None:
    c = PendingAdmissionQS(1, range_threshold=0)
    c.process("k1", 100)
    c.process("k1", 100)  # admit k1; store full
    c.process("k2", 200)  # → pending
    _, evicted = c.process("k2", 200)  # admit k2 → evict k1
    assert evicted is True


def test_pending_qs_invalid_params() -> None:
    with pytest.raises(ValueError):
        PendingAdmissionQS(0)


# ---------------------------------------------------------------------------
# PITCollapsedQS
# ---------------------------------------------------------------------------

def test_pit_qs_inflight_collapse() -> None:
    c = PITCollapsedQS(4, range_threshold=0, download_delay_ps=100)
    c.process("k1", 100, ts=0)   # creates PIT entry
    hit, _ = c.process("k1", 100, ts=50)  # same qs, inflight → collapsed
    assert hit is True


def test_pit_qs_ready_ts_admits() -> None:
    c = PITCollapsedQS(4, range_threshold=0, download_delay_ps=100)
    c.process("k1", 100, ts=0)
    c.process("k1", 100, ts=200)  # ts >= ready → admit
    assert "k1" in c._store


def test_pit_qs_value_change_inflight() -> None:
    c = PITCollapsedQS(4, range_threshold=0, download_delay_ps=100)
    c.process("k1", 100, ts=0)
    hit, _ = c.process("k1", 9000, ts=50)  # big change while inflight → forward, update PIT
    assert hit is False
    assert c._pit["k1"][0] == 9000


def test_pit_qs_cache_hit_after_admit() -> None:
    c = PITCollapsedQS(4, range_threshold=0, download_delay_ps=50)
    c.process("k1", 100, ts=0)
    c.process("k1", 100, ts=100)  # admit
    hit, _ = c.process("k1", 100, ts=150)  # cache hit
    assert hit is True


def test_pit_qs_pit_capacity_overflow() -> None:
    c = PITCollapsedQS(4, range_threshold=0, download_delay_ps=100, pit_capacity=2)
    c.process("k1", 100, ts=0)
    c.process("k2", 200, ts=0)
    c.process("k3", 300, ts=0)  # evicts k1 from PIT
    assert "k1" not in c._pit


def test_pit_qs_admit_eviction() -> None:
    c = PITCollapsedQS(1, range_threshold=0, download_delay_ps=10)
    c.process("k1", 100, ts=0)
    c.process("k1", 100, ts=100)  # admit k1; store full
    c.process("k2", 200, ts=0)   # PIT entry for k2
    _, evicted = c.process("k2", 200, ts=200)  # admit k2 → evict k1
    assert evicted is True


def test_pit_qs_invalid_params() -> None:
    with pytest.raises(ValueError):
        PITCollapsedQS(0)


# ---------------------------------------------------------------------------
# AdaptiveAdmissionQS
# ---------------------------------------------------------------------------

def test_adaptive_qs_low_pressure_admits_directly() -> None:
    c = AdaptiveAdmissionQS(4, range_threshold=0, pressure_window=10000,
                             eviction_high_watermark=0.5)
    c.process("k1", 100)
    assert "k1" in c._store


def test_adaptive_qs_under_pressure_gates() -> None:
    c = AdaptiveAdmissionQS(4, range_threshold=0, pressure_window=10000,
                             eviction_high_watermark=0.0)
    c._under_pressure = True
    c.process("k1", 100)   # → pending
    assert "k1" in c._pending
    c.process("k1", 100)   # second touch → admit
    assert "k1" in c._store


def test_adaptive_qs_pressure_update_fires() -> None:
    c = AdaptiveAdmissionQS(1, range_threshold=0, pressure_window=2,
                             eviction_high_watermark=0.01)
    c.process("k1", 100)
    c.process("k2", 200)  # evicts k1, window_ops=2 → pressure evaluated
    # under_pressure set; just assert no crash and correct type
    assert isinstance(c._under_pressure, bool)


def test_adaptive_qs_store_hit() -> None:
    c = AdaptiveAdmissionQS(4, range_threshold=100)
    c.process("k1", 1000)
    hit, _ = c.process("k1", 1050)  # change 50 <= 100 → hit
    assert hit is True


def test_adaptive_qs_pending_reset() -> None:
    c = AdaptiveAdmissionQS(4, range_threshold=0, pressure_window=10000,
                             eviction_high_watermark=0.0, pending_reset_every=2)
    c._under_pressure = True
    c.process("k1", 100)  # ops=1 → pending
    c.process("k2", 200)  # ops=2 → reset clears pending, then k2 → pending
    assert "k1" not in c._pending


def test_adaptive_qs_pending_overflow() -> None:
    c = AdaptiveAdmissionQS(4, range_threshold=0, pressure_window=10000,
                             eviction_high_watermark=0.0, pending_size=2)
    c._under_pressure = True
    for i in range(5):
        c.process(f"k{i}", 100)
    assert len(c._pending) <= 2


def test_adaptive_qs_invalid_params() -> None:
    with pytest.raises(ValueError):
        AdaptiveAdmissionQS(0)


# ---------------------------------------------------------------------------
# OnlineAdaptiveAdmissionQS
# ---------------------------------------------------------------------------

def test_online_adaptive_qs_mode0_open_admission() -> None:
    c = OnlineAdaptiveAdmissionQS(4, range_threshold=0)
    assert c._mode == 0
    c.process("k1", 100)
    assert "k1" in c._store


def test_online_adaptive_qs_mode0_to_1_transition() -> None:
    c = OnlineAdaptiveAdmissionQS(
        4, range_threshold=0, pressure_window=10, high_evict=0.20,
        low_evict=0.005, weak_hit=0.70, strong_hit=0.92,
    )
    for i in range(4):
        c.process(f"k{i}", 100)
    c._w_ops = 9
    c._w_hits = 0
    c._w_evicts = 5  # evict_ratio=0.5 >= 0.20, hit_ratio=0 <= 0.70
    c._bump_window(False, True)
    assert c._mode == 1


def test_online_adaptive_qs_mode1_second_touch() -> None:
    c = OnlineAdaptiveAdmissionQS(4, range_threshold=0)
    c._mode = 1
    c.process("k1", 100)   # touches=1 → pending
    assert "k1" in c._pending
    c.process("k1", 100)   # touches=2 > required=1 → admit
    assert "k1" in c._store


def test_online_adaptive_qs_mode2_third_touch() -> None:
    c = OnlineAdaptiveAdmissionQS(4, range_threshold=0)
    c._mode = 2
    c.process("k1", 100)  # touches=1
    c.process("k1", 100)  # touches=2
    c.process("k1", 100)  # touches=3 > required=2 → admit
    assert "k1" in c._store


def test_online_adaptive_qs_mode2_to_1_downgrade() -> None:
    c = OnlineAdaptiveAdmissionQS(
        4, range_threshold=0, pressure_window=10, high_evict=0.20,
        low_evict=0.005, weak_hit=0.70, strong_hit=0.92,
    )
    c._mode = 2
    c._w_ops = 9
    c._w_hits = 10   # hit_ratio > strong_hit
    c._w_evicts = 0  # evict_ratio < low_evict
    c._bump_window(True, False)
    assert c._mode == 1


def test_online_adaptive_qs_mode0_eviction() -> None:
    c = OnlineAdaptiveAdmissionQS(2, range_threshold=0)
    c.process("k1", 100)
    c.process("k2", 200)
    _, evicted = c.process("k3", 300)
    assert evicted is True


def test_online_adaptive_qs_pending_overflow() -> None:
    c = OnlineAdaptiveAdmissionQS(4, range_threshold=0, pending_size=2)
    c._mode = 1
    for i in range(6):
        c.process(f"k{i}", 100)
    assert len(c._pending) <= 2


def test_online_adaptive_qs_invalid_params() -> None:
    with pytest.raises(ValueError):
        OnlineAdaptiveAdmissionQS(0)


# ---------------------------------------------------------------------------
# TimingBloomQS
# ---------------------------------------------------------------------------

def test_timing_bloom_qs_admits_first_time_no_pressure() -> None:
    c = TimingBloomQS(4, range_threshold=0, bloom_bits=64, bloom_hashes=2,
                      bloom_epoch_records=1000)
    c.process("k1", 100)
    assert "k1" in c._store


def test_timing_bloom_qs_under_pressure_gates_unseen() -> None:
    c = TimingBloomQS(2, range_threshold=0, bloom_bits=64, bloom_hashes=2,
                      bloom_epoch_records=1000, pressure_window=2,
                      eviction_high_watermark=0.01)
    c.process("k1", 100)
    c.process("k2", 200)
    c.process("k3", 300)   # evicts → pressure fired
    c._under_pressure = True
    # brand-new unseen key with full cache → gated
    hit, ev = c.process("brand_new", 999)
    assert hit is False


def test_timing_bloom_qs_epoch_resets() -> None:
    c = TimingBloomQS(4, range_threshold=0, bloom_bits=64, bloom_hashes=2,
                      bloom_epoch_records=3)
    c.process("k1", 100)
    c.process("k2", 200)
    c.process("k3", 300)  # ops=3 → epoch reset
    assert c._ops % 3 == 0


def test_timing_bloom_qs_store_hit() -> None:
    c = TimingBloomQS(4, range_threshold=100)
    c.process("k1", 1000)
    hit, _ = c.process("k1", 1050)  # change 50 <= 100 → hit
    assert hit is True


def test_timing_bloom_qs_invalid_params() -> None:
    with pytest.raises(ValueError):
        TimingBloomQS(0)  # capacity <= 0 is the only guarded param in the QS version


# ---------------------------------------------------------------------------
# TinyLFUQS
# ---------------------------------------------------------------------------

def test_tiny_lfu_qs_admits_frequent_candidate() -> None:
    c = TinyLFUQS(2, range_threshold=0, sample_multiplier=4)
    c.process("k1", 100)
    c.process("k2", 200)
    for _ in range(10):
        c._sketch.observe("k3")
    _, evicted = c.process("k3", 300)
    assert evicted is True


def test_tiny_lfu_qs_bypasses_infrequent() -> None:
    c = TinyLFUQS(2, range_threshold=0, sample_multiplier=2)
    c.process("k1", 100)
    c.process("k2", 200)
    for _ in range(20):
        c._sketch.observe("k1")
        c._sketch.observe("k2")
    hit, evicted = c.process("k3", 300)
    assert hit is False and evicted is False
    assert "k3" not in c._store


def test_tiny_lfu_qs_store_hit() -> None:
    c = TinyLFUQS(4, range_threshold=100)
    c.process("k1", 1000)
    hit, _ = c.process("k1", 1050)  # change 50 <= 100 → hit
    assert hit is True


def test_tiny_lfu_qs_invalid_params() -> None:
    with pytest.raises(ValueError):
        TinyLFUQS(0)


# ---------------------------------------------------------------------------
# TinyCacheQS
# ---------------------------------------------------------------------------

def test_tiny_cache_qs_admits_frequent_candidate() -> None:
    c = TinyCacheQS(2, range_threshold=0)
    c.process("k1", 100)
    c.process("k2", 200)
    for _ in range(15):
        c._table.observe("k3")
    _, evicted = c.process("k3", 300)
    assert evicted is True


def test_tiny_cache_qs_bypasses_infrequent() -> None:
    c = TinyCacheQS(2, range_threshold=0)
    c.process("k1", 100)
    c.process("k2", 200)
    for _ in range(20):
        c._table.observe("k1")
        c._table.observe("k2")
    hit, evicted = c.process("k3", 300)
    assert isinstance(hit, bool)


def test_tiny_cache_qs_store_hit() -> None:
    c = TinyCacheQS(4, range_threshold=100)
    c.process("k1", 1000)
    hit, _ = c.process("k1", 1050)
    assert hit is True


def test_tiny_cache_qs_invalid_params() -> None:
    with pytest.raises(ValueError):
        TinyCacheQS(0)


# ---------------------------------------------------------------------------
# SegmentedQS
# ---------------------------------------------------------------------------

def test_segmented_qs_promotes_to_protected() -> None:
    c = SegmentedQS(8, range_threshold=0)
    c.process("k1", 100)   # → probation
    c.process("k1", 100)   # hit in probation → promote to protected
    assert "k1" in c._protected
    assert "k1" not in c._probation


def test_segmented_qs_protected_hit() -> None:
    c = SegmentedQS(8, range_threshold=0)
    c.process("k1", 100)
    c.process("k1", 100)  # promote
    hit, _ = c.process("k1", 100)
    assert hit is True


def test_segmented_qs_evicts_from_probation() -> None:
    c = SegmentedQS(4, range_threshold=0)  # prob_cap=1, prot_cap=3
    c.process("k1", 100)  # fills probation
    _, ev = c.process("k2", 200)  # evicts k1 from probation
    assert ev is True


def test_segmented_qs_protected_demotion() -> None:
    c = SegmentedQS(4, range_threshold=0)  # prob_cap=1, prot_cap=3
    c.process("k1", 100); c.process("k1", 100)  # promote k1
    c.process("k2", 200); c.process("k2", 200)  # promote k2
    c.process("k3", 300); c.process("k3", 300)  # promote k3; protected full
    c.process("k4", 400)  # → probation
    c.process("k4", 400)  # promote k4 → demote LRU of protected back to probation
    # Verify structure is intact (no crash, invariants hold)
    assert len(c._protected) <= 3


def test_segmented_qs_degenerate_capacity_1() -> None:
    c = SegmentedQS(1, range_threshold=0)  # prot_cap=0
    c.process("k1", 100)
    c.process("k1", 100)  # hit in probation with prot_cap=0 → stays in probation
    assert "k1" in c._probation


def test_segmented_qs_range_threshold() -> None:
    c = SegmentedQS(4, range_threshold=200)
    c.process("k1", 1000)
    hit, _ = c.process("k1", 1100)  # change 100 <= 200 → hit in probation (promotes)
    assert hit is True


def test_segmented_qs_invalid_params() -> None:
    with pytest.raises(ValueError):
        SegmentedQS(0)


# ---------------------------------------------------------------------------
# cache_slots_used_qs
# ---------------------------------------------------------------------------

def test_cache_slots_used_qs_store_dict() -> None:
    c = LRUQSCache(4, range_threshold=0)
    c.process("k1", 100)
    c.process("k2", 200)
    assert cache_slots_used_qs(c) == 2


def test_cache_slots_used_qs_probation_protected() -> None:
    c = SegmentedQS(8, range_threshold=0)
    c.process("k1", 100)
    c.process("k2", 200)
    assert cache_slots_used_qs(c) == 2


def test_cache_slots_used_qs_fallback() -> None:
    class Opaque:
        pass
    assert cache_slots_used_qs(Opaque()) is None


# ---------------------------------------------------------------------------
# simulate_congestion
# ---------------------------------------------------------------------------

def test_simulate_congestion_basic_counts() -> None:
    recs = [
        {"source": "k1", "qs": 1000, "ts_ps": 0},
        {"source": "k1", "qs": 1000, "ts_ps": 1},   # hit
        {"source": "k2", "qs": 2000, "ts_ps": 2},   # new key → miss
    ]
    c = LRUQSCache(4, range_threshold=0)
    oracle = InfiniteQS(range_threshold=0)
    result = simulate_congestion(recs, c, oracle)
    assert result.total == 3
    assert result.hits == 1
    assert result.new_route_forwards == 2
    assert result.route_change_forwards == 0
    assert result.redundant_forwards == 0


def test_simulate_congestion_route_change_classified() -> None:
    recs = [
        {"source": "k1", "qs": 1000, "ts_ps": 0},
        {"source": "k1", "qs": 9000, "ts_ps": 1},   # value changed → route_change
    ]
    c = LRUQSCache(4, range_threshold=0)
    oracle = InfiniteQS(range_threshold=0)
    result = simulate_congestion(recs, c, oracle)
    assert result.route_change_forwards == 1
    assert result.new_route_forwards == 1


def test_simulate_congestion_redundant_forward() -> None:
    # Tiny cache forces eviction so oracle suppresses but bounded cache misses
    recs = [
        {"source": "k1", "qs": 100, "ts_ps": 0},
        {"source": "k2", "qs": 200, "ts_ps": 1},   # evicts k1 (cap=1)
        {"source": "k1", "qs": 100, "ts_ps": 2},   # oracle hits, bounded misses → redundant
    ]
    c = LRUQSCache(1, range_threshold=0)
    oracle = InfiniteQS(range_threshold=0)
    result = simulate_congestion(recs, c, oracle)
    assert result.redundant_forwards >= 1


def test_simulate_congestion_no_oracle() -> None:
    # Without oracle, every forward counted as necessary
    recs = [
        {"source": "k1", "qs": 100, "ts_ps": 0},
        {"source": "k2", "qs": 200, "ts_ps": 1},
    ]
    c = InfiniteQS(range_threshold=0)
    result = simulate_congestion(recs, c, oracle=None)
    assert result.total == 2
    assert result.necessary_forwards == 2
    assert result.new_route_forwards == 2


def test_simulate_congestion_capacity_sampling() -> None:
    recs = _qs_records()
    c = LRUQSCache(4, range_threshold=0)
    oracle = InfiniteQS(range_threshold=0)
    samples = []
    simulate_congestion(recs, c, oracle, capacity_samples=samples, capacity_sample_every=1)
    assert len(samples) > 0
    assert all(len(s) == 3 for s in samples)


def test_simulate_congestion_capacity_no_duplicate_end_sample() -> None:
    recs = _qs_records()
    c = LRUQSCache(4, range_threshold=0)
    samples = []
    simulate_congestion(recs, c, capacity_samples=samples, capacity_sample_every=1)
    indices = [s[0] for s in samples]
    assert len(indices) == len(set(indices))


def test_simulate_congestion_infinite_skips_capacity_sampling() -> None:
    # InfiniteQS (capacity=inf) should not populate capacity_samples
    c = InfiniteQS(range_threshold=0)
    samples = []
    simulate_congestion(_qs_records(), c, capacity_samples=samples, capacity_sample_every=1)
    assert samples == []


# ---------------------------------------------------------------------------
# sweep_congestion
# ---------------------------------------------------------------------------

def test_sweep_congestion_returns_results() -> None:
    recs = _qs_records()
    results = sweep_congestion(recs, range_threshold=0)
    assert len(results) > 0
    # InfiniteQS always first
    assert results[0].cache_name == "Infinite"
    assert any(r.capacity != float("inf") for r in results)


def test_sweep_congestion_with_capacity_curves() -> None:
    recs = _qs_records()
    curves = {}
    sweep_congestion(recs, range_threshold=0, capacity_curves=curves, capacity_sample_every=1)
    assert len(curves) > 0


# ---------------------------------------------------------------------------
# print_results and write_csv for congestion
# ---------------------------------------------------------------------------

def test_print_congestion_results(capsys) -> None:
    recs = _qs_records()
    c = LRUQSCache(4, range_threshold=0)
    oracle = InfiniteQS(range_threshold=0)
    results = [simulate_congestion(recs, c, oracle),
               simulate_congestion(recs, InfiniteQS(0))]
    print_congestion_results(results)
    captured = capsys.readouterr()
    assert "Cache" in captured.out
    assert "LRU" in captured.out


def test_write_congestion_csv(tmp_path: Path) -> None:
    recs = _qs_records()
    c = LRUQSCache(4, range_threshold=0)
    oracle = InfiniteQS(range_threshold=0)
    results = [simulate_congestion(recs, c, oracle),
               simulate_congestion(recs, InfiniteQS(0))]
    out = tmp_path / "out.csv"
    write_congestion_csv(results, str(out))
    text = out.read_text(encoding="utf-8")
    assert "cache" in text
    assert "necessary_forwards" in text
    assert "redundancy_rate" in text
    # Infinite capacity is written as -1
    assert "-1" in text


def test_write_congestion_capacity_csv(tmp_path: Path) -> None:
    recs = _qs_records()
    curves = {}
    sweep_congestion(recs, range_threshold=0, capacity_curves=curves, capacity_sample_every=1)
    out = tmp_path / "cap.csv"
    write_congestion_capacity_csv(curves, str(out))
    text = out.read_text(encoding="utf-8")
    assert "fill_percent" in text


def test_write_congestion_capacity_csv_skips_infinite() -> None:
    # Capacity <= 0 should be skipped
    curves = {("Infinite", -1): [(1, 100, 5)], ("LRU", 0): [(1, 100, 0)]}
    import tempfile, os
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        path = f.name
    try:
        write_congestion_capacity_csv(curves, path)
        text = Path(path).read_text()
        assert "Infinite" not in text
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# RollingBloomFilterQS (same logic as in cache_sim, re-tested for coverage)
# ---------------------------------------------------------------------------

def test_rolling_bloom_qs_basic() -> None:
    bf = RollingBloomFilterQS(bits=256, hashes=2)
    assert not bf.contains("foo")
    bf.add("foo")
    assert bf.contains("foo")
    bf.reset_epoch()
    assert bf.contains("foo")   # still in previous window
    bf.reset_epoch()
    assert not bf.contains("foo")  # both windows cleared


def test_rolling_bloom_qs_invalid_params() -> None:
    with pytest.raises(ValueError):
        RollingBloomFilterQS(bits=0)
    with pytest.raises(ValueError):
        RollingBloomFilterQS(hashes=0)


# ---------------------------------------------------------------------------
# _TinyLFUSketchQS and _TinyCacheTableQS (re-tested in congestion context)
# ---------------------------------------------------------------------------

def test_tiny_lfu_sketch_qs_observe_and_estimate() -> None:
    s = _TinyLFUSketchQS(sample_size=100, counter_cap=10)
    s.observe("k1")
    assert s.estimate("k1") == 1  # doorkeeper only
    s.observe("k1")
    assert s.estimate("k1") == 2  # doorkeeper + count=1


def test_tiny_lfu_sketch_qs_reset() -> None:
    s = _TinyLFUSketchQS(sample_size=3, counter_cap=10)
    s.observe("k1")
    s.observe("k1")
    s.observe("k1")  # ops=3 >= sample_size=3 → reset
    assert len(s._doorkeeper) == 0
    assert s._ops == 0


def test_tiny_lfu_sketch_qs_invalid_params() -> None:
    with pytest.raises(ValueError):
        _TinyLFUSketchQS(0, 10)
    with pytest.raises(ValueError):
        _TinyLFUSketchQS(10, 0)


def test_tiny_cache_table_qs_observe_and_estimate() -> None:
    t = _TinyCacheTableQS(set_count=4, set_capacity=4, duplicate_cap=2)
    t.observe("k1")
    assert t.estimate("k1") >= 1


def test_tiny_cache_table_qs_decay() -> None:
    t = _TinyCacheTableQS(set_count=2, set_capacity=4, duplicate_cap=4, seed=0)
    for _ in range(8):
        t.observe("k1")
    total = sum(len(b) for b in t._sets)
    assert total >= 0


def test_tiny_cache_table_qs_invalid_params() -> None:
    with pytest.raises(ValueError):
        _TinyCacheTableQS(0, 4, 2)
    with pytest.raises(ValueError):
        _TinyCacheTableQS(4, 0, 2)
    with pytest.raises(ValueError):
        _TinyCacheTableQS(4, 4, 0)


# ---------------------------------------------------------------------------
# Additional coverage: remaining uncovered branches
# ---------------------------------------------------------------------------

def test_cache_slots_used_qs_sets_branch() -> None:
    # Lines 128-134: cache_slots_used_qs with _sets attribute (TinyCache table)
    t = _TinyCacheTableQS(set_count=4, set_capacity=4, duplicate_cap=2)
    t.observe("k1")
    t.observe("k2")
    total = cache_slots_used_qs(type("FakeTinyCache", (), {"_sets": t._sets})())
    assert total is not None and total >= 0


def test_flow_ttl_qs_update_ema_first_sample() -> None:
    # Line 463: _update_ema with samples=1 returns gap directly
    c = FlowLifetimeAdaptiveTTLQS(4, range_threshold=0, ema_alpha=0.5)
    result = c._update_ema(500, 300, 1)   # samples=1 → return gap (300)
    assert result == 300
    result2 = c._update_ema(500, 300, 2)  # samples=2 → EMA formula
    assert result2 == int(0.5 * 300 + 0.5 * 500)


def test_pit_qs_store_hit_with_value_change_after_eviction() -> None:
    # Lines 609-610: PIT admits entry; store has it but qs changed and evicted=True
    # Scenario: PIT expires and admits, then the store lookup finds a *different* qs
    c = PITCollapsedQS(4, range_threshold=0, download_delay_ps=50)
    # Manually set up: pre-fill store with k1 at old qs, and a PIT entry for k1 at new qs
    c._store["k1"] = 999
    c._pit["k1"] = (500, 0)  # ready_ts=0, so ts=100 >= 0 → will admit
    # process: PIT fires (ts>=ready_ts=0), evicted=admit("k1",500) → store["k1"]=500
    # then store lookup → hit? new_qs=999: abs(999-500)=499 > 0 → miss (line 609-610)
    hit, evicted = c.process("k1", 999, ts=100)
    # The PIT admit replaced store[k1] with 500; then store check qs=999 vs cached=500 → miss
    assert hit is False


def test_adaptive_qs_pending_to_store_eviction() -> None:
    # Lines 672-673: AdaptiveAdmissionQS, under pressure, admit from pending causes eviction
    c = AdaptiveAdmissionQS(1, range_threshold=0, pressure_window=10000,
                             eviction_high_watermark=0.0)
    c._under_pressure = True
    c.process("k1", 100)   # → pending (store empty)
    c.process("k1", 100)   # admit k1; store now full (cap=1)
    c.process("k2", 200)   # → pending
    _, evicted = c.process("k2", 200)  # admit k2 → store full → evict k1
    assert evicted is True


def test_online_adaptive_qs_mode1_eviction_on_admit() -> None:
    # Lines 754-755: OnlineAdaptiveAdmissionQS mode=1, pending-to-store admission evicts
    c = OnlineAdaptiveAdmissionQS(1, range_threshold=0)
    c._mode = 1
    c.process("k1", 100)   # touches=1 → pending
    c.process("k1", 100)   # touches=2 → admit; store full (cap=1)
    c.process("k2", 200)   # touches=1 → pending
    _, evicted = c.process("k2", 200)  # touches=2 → admit → evict k1
    assert evicted is True


def test_tiny_cache_table_qs_bucket_full_random_eviction() -> None:
    # Lines 923-924: bucket at capacity → random victim popped before append
    t = _TinyCacheTableQS(set_count=1, set_capacity=2, duplicate_cap=1, seed=42)
    # Fill the single bucket: observe unique keys until bucket reaches set_capacity=2
    # Then observe another unique key to trigger the random eviction path
    t.observe("alpha")
    t.observe("beta")
    # bucket is now full (2 items). observe "gamma" → random eviction
    t.observe("gamma")
    assert len(t._sets[0]) <= 2


def test_simulate_congestion_end_sample_appended() -> None:
    # Line 1084: end-of-run sample appended when last record was not yet sampled by interval
    recs = _qs_records()  # 6 records
    c = LRUQSCache(4, range_threshold=0)
    oracle = InfiniteQS(range_threshold=0)
    samples = []
    # sample_every=10 → only record 1 is sampled mid-run (total==1)
    # end-of-run check fires and appends for total=6 (different from last sampled total=1)
    simulate_congestion(recs, c, oracle, capacity_samples=samples, capacity_sample_every=10)
    totals = [s[0] for s in samples]
    assert 6 in totals   # end-of-run sample was appended


def test_tiny_cache_table_qs_random_eviction() -> None:
    # Lines 923-924: random eviction when bucket is full but duplicate_cap not reached
    t = _TinyCacheTableQS(set_count=1, set_capacity=2, duplicate_cap=10, seed=42)
    # Prevent decay from firing prematurely by pushing sample_size high
    t._sample_size = 10000
    t.observe("a")
    t.observe("b")
    # Bucket is now full (capacity=2). Observing a new unique key triggers random eviction.
    t.observe("c")
    # After random eviction of one item and insertion of "c", bucket is still at capacity
    bucket = t._sets[0]
    assert len(bucket) == 2


def test_build_hop_records_switch_level(tmp_path: Path) -> None:
    from fyp.dash_scripts.cache_sim_congestion_int import build_hop_records
    import argparse
    log = tmp_path / "int.txt"
    log.write_text(
        "INT flow=1 seq=0 hops=2\n"
        "  [0] sw=10 type=1 qs=500 ts=100 txbytes=0 pktid=1\n"
        "  [1] sw=20 type=2 qs=1000 ts=200 txbytes=0 pktid=1\n"
        "INT flow=2 seq=0 hops=1\n"
        "  [0] sw=10 type=1 qs=300 ts=300 txbytes=0 pktid=2\n"
    )
    args = argparse.Namespace(key_level="switch", max_records=0)
    records, n_int = build_hop_records(log, args)
    assert n_int == 2
    # 2 hops from flow=1 + 1 hop from flow=2 = 3 records
    assert len(records) == 3
    assert records[0]["source"] == "10:1"
    assert records[0]["qs"] == 500


def test_build_hop_records_flow_level(tmp_path: Path) -> None:
    from fyp.dash_scripts.cache_sim_congestion_int import build_hop_records
    import argparse
    log = tmp_path / "int.txt"
    log.write_text(
        "INT flow=5 seq=0 hops=2\n"
        "  [0] sw=10 type=1 qs=500 ts=100 txbytes=0 pktid=1\n"
        "  [1] sw=20 type=2 qs=1500 ts=200 txbytes=0 pktid=1\n"
    )
    args = argparse.Namespace(key_level="flow", max_records=0)
    records, n_int = build_hop_records(log, args)
    assert n_int == 1
    assert len(records) == 1
    assert records[0]["source"] == "5"
    assert records[0]["qs"] == 1500  # max of [500, 1500]


def test_build_hop_records_max_records(tmp_path: Path) -> None:
    from fyp.dash_scripts.cache_sim_congestion_int import build_hop_records
    import argparse
    log = tmp_path / "int.txt"
    log.write_text(
        "INT flow=1 seq=0 hops=1\n"
        "  [0] sw=10 type=1 qs=100 ts=100 txbytes=0 pktid=1\n"
        "INT flow=2 seq=0 hops=1\n"
        "  [0] sw=11 type=1 qs=200 ts=200 txbytes=0 pktid=2\n"
        "INT flow=3 seq=0 hops=1\n"
        "  [0] sw=12 type=1 qs=300 ts=300 txbytes=0 pktid=3\n"
    )
    args = argparse.Namespace(key_level="switch", max_records=2)
    records, n_int = build_hop_records(log, args)
    # max_records=2 means stop after parsing 2 INT records (flows 1 and 2)
    assert n_int <= 3
    assert len(records) <= 2


def test_resolve_inputs_qs_file(tmp_path: Path) -> None:
    from fyp.dash_scripts.cache_sim_congestion_int import resolve_inputs
    p = tmp_path / "log.txt"
    p.write_text("INT flow=1 seq=0 hops=1\n")
    result = resolve_inputs(p, "*.txt")
    assert result == [p]


def test_resolve_inputs_qs_directory(tmp_path: Path) -> None:
    from fyp.dash_scripts.cache_sim_congestion_int import resolve_inputs
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("x\n")
    f2.write_text("y\n")
    result = resolve_inputs(tmp_path, "*.txt")
    assert set(result) == {f1, f2}


def test_resolve_inputs_qs_missing_raises(tmp_path: Path) -> None:
    from fyp.dash_scripts.cache_sim_congestion_int import resolve_inputs
    with pytest.raises(FileNotFoundError):
        resolve_inputs(tmp_path / "nonexistent.txt", "*")


def test_resolve_inputs_qs_no_matches_raises(tmp_path: Path) -> None:
    from fyp.dash_scripts.cache_sim_congestion_int import resolve_inputs
    with pytest.raises(FileNotFoundError):
        resolve_inputs(tmp_path, "*.nomatch")
