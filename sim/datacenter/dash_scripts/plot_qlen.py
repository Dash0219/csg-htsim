import re
import matplotlib.pyplot as plt
from collections import defaultdict

LOG = "log2.txt"

# Pick the switch you want to plot
TARGET_SWITCH = 42   # change this
TARGET_TYPE = None   # set to 1/2/3 or None for all

hop_re = re.compile(
    r"hop \d+ switch=(\d+) switchtype=(\d+) qlen=(\d+) ts=(\d+)"
)

samples = []

with open(LOG) as f:
    for line in f:
        m = hop_re.search(line)
        if not m:
            continue

        sw, stype, qlen, ts = map(int, m.groups())

        if sw != TARGET_SWITCH:
            continue
        if TARGET_TYPE is not None and stype != TARGET_TYPE:
            continue

        samples.append((ts, qlen, stype))

if not samples:
    print("No samples found for this switch")
    exit(0)

# sort by time
samples.sort()

ts = [(t - samples[0][0]) / 1e6 for t, _, _ in samples]  # convert to ms
qlen = [q for _, q, _ in samples]

plt.figure(figsize=(10, 4))
plt.plot(ts, qlen, marker='.', linestyle='-')
plt.xlabel("Time (ms)")
plt.ylabel("Queue length (bytes)")
plt.title(f"Switch {TARGET_SWITCH} queue length over time")
plt.grid(True)
plt.tight_layout()
plt.show()
