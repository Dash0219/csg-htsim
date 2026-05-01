# import re
# from collections import defaultdict, Counter

# LOG = "log2.txt"

# # Regexes
# flow_re = re.compile(r"Printing INT info for flow (\d+), sink: (\d+), no\. of hops: (\d+)")
# hop_re = re.compile(
#     r"hop \d+ switch=(\d+) switchtype=(\d+) qlen=(\d+) ts=(\d+) txbytes=(\d+).*packetid=(\d+)"
# )

# # Data stores
# switch_samples = defaultdict(list)   # (switch, type) -> [(ts, qlen)]
# path_types = Counter()
# path_lengths = Counter()

# current_path = []
# current_len = None
# cache = defaultdict()

# with open(LOG) as f:
#     for line in f:
#         m = flow_re.search(line)
#         if m:
#             if current_path:
#                 path_types[tuple(current_path)] += 1
#                 path_lengths[current_len] += 1
#             current_path = []
#             current_len = int(m.group(3))
#             continue

#         m = hop_re.search(line)
#         if m:
#             sw, stype, qlen, ts, tx, pkt = m.groups()
#             sw = int(sw)
#             stype = int(stype)
#             qlen = int(qlen)
#             ts = int(ts)

#             switch_samples[(sw, stype)].append((ts, qlen))
#             current_path.append(stype)

# # flush last path
# if current_path:
#     path_types[tuple(current_path)] += 1
#     path_lengths[current_len] += 1

# print("==== PATH LENGTH DISTRIBUTION ====")
# for k in sorted(path_lengths):
#     print(f"{k} hops: {path_lengths[k]} paths")

# print("\n==== MOST COMMON PATH TYPES (switch types) ====")
# for p, c in path_types.most_common(5):
#     print(p, "count =", c)

# print("\n==== CACHE HIT ESTIMATION (Δqlen ≤ 1 MTU = 9064) ====")
# DELTA = 9064

# hit = 0
# miss = 0

# for key, samples in switch_samples.items():
#     # Dash: i think i don't sort here, cuz i'm simulating real time arrival order
#     # samples.sort()
#     last_q = None
#     for _, q in samples:
#         if last_q is None:
#             miss += 1
#         else:
#             if abs(q - last_q) <= DELTA:
#                 hit += 1
#             else:
#                 miss += 1
#         last_q = q

# total = hit + miss
# print(f"Total samples: {total}")
# print(f"Cache hits: {hit}")
# print(f"Cache misses: {miss}")
# print(f"Estimated hit ratio: {hit/total:.3f}")

# print("\n==== PER-SWITCH STABILITY (top 10) ====")
# stability = []
# for key, samples in switch_samples.items():
#     qlens = [q for _, q in samples]
#     changes = sum(1 for i in range(1, len(qlens)) if qlens[i] != qlens[i-1])
#     stability.append((key, len(samples), changes))

# stability.sort(key=lambda x: x[2])

# for (sw, st), total_s, ch in stability[:10]:
#     print(f"switch {sw} type {st}: samples={total_s}, qlen_changes={ch}")


import re
from collections import defaultdict, Counter

LOG = "log2.txt"
DELTA = 9064  # 1 MTU for cache hit estimation

# Regex patterns
flow_re = re.compile(r"Printing INT info for flow (\d+), sink: (\d+), no\. of hops: (\d+)")
hop_re = re.compile(
    r"hop \d+ switch=(\d+) switchtype=(\d+) qlen=(\d+) ts=(\d+) txbytes=(\d+).*packetid=(\d+)"
)

# Data stores
switch_cache = {}  # (switch, type) -> {'qlen':..., 'ts':..., 'txbytes':...}
switch_samples = defaultdict(list)  # (switch, type) -> [(ts, qlen)]
path_types = Counter()
path_lengths = Counter()

current_path = []
current_len = None

hit = 0
miss = 0

with open(LOG) as f:
    for line in f:
        m = flow_re.search(line)
        if m:
            if current_path:
                path_types[tuple(current_path)] += 1
                path_lengths[current_len] += 1
            current_path = []
            current_len = int(m.group(3))
            continue

        m = hop_re.search(line)
        if m:
            sw, stype, qlen, ts, tx, pkt = m.groups()
            sw = int(sw)
            stype = int(stype)
            qlen = int(qlen)
            ts = int(ts)
            tx = int(tx)

            current_path.append(stype)

            key = (sw, stype)
            if key in switch_cache:
                cached = switch_cache[key]
                if abs(cached['qlen'] - qlen) <= DELTA:
                    hit += 1
                else:
                    miss += 1
                    switch_cache[key] = {'qlen': qlen, 'ts': ts, 'txbytes': tx}
            else:
                miss += 1
                switch_cache[key] = {'qlen': qlen, 'ts': ts, 'txbytes': tx}

            switch_samples[key].append((ts, qlen))

if current_path:
    path_types[tuple(current_path)] += 1
    path_lengths[current_len] += 1

# === OUTPUT ===
print("==== PATH LENGTH DISTRIBUTION ====")
for k in sorted(path_lengths):
    print(f"{k} hops: {path_lengths[k]} paths")

print("\n==== MOST COMMON PATH TYPES (switch types) ====")
for p, c in path_types.most_common(5):
    print(p, "count =", c)

print("\n==== CACHE HIT ESTIMATION (Δqlen ≤ 1 MTU = 9064) ====")
total = hit + miss
print(f"Total samples: {total}")
print(f"Cache hits: {hit}")
print(f"Cache misses: {miss}")
print(f"Estimated hit ratio: {hit/total:.3f}")

print("\n==== PER-SWITCH STABILITY (top 10) ====")
stability = []
for key, samples in switch_samples.items():
    qlens = [q for _, q in samples]
    changes = sum(1 for i in range(1, len(qlens)) if qlens[i] != qlens[i-1])
    stability.append((key, len(samples), changes))

stability.sort(key=lambda x: x[2])
for (sw, st), total_s, ch in stability[:10]:
    print(f"switch {sw} type {st}: samples={total_s}, qlen_changes={ch}")
