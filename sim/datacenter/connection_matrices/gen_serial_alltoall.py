#!/usr/bin/env python

# Generate a permutation traffic matrix.
# python gen_pemutation.py <nodes> <conns> <groupsize> <flowsize> <extrastarttime>
# Parameters:
# <nodes>   number of nodes in the topology
# <conns>    number of active connections
# <groupsize>    number of connections in an all-to-all group
# <flowsize>   size of the flows in bytes
# <extrastarttime>   How long in microseconds to space the start times over (start time will be random in between 0 and this time).  Can be a float.
# <randseed>   Seed for random number generator, or set to 0 for random seed

import os
import sys
from random import seed, shuffle, random, paretovariate, lognormvariate, expovariate, randint
#print(sys.argv)


def parse_size_dist(spec, default_flowsize):
    if not spec or spec == "fixed":
        return ("fixed", {"size": default_flowsize})

    parts = spec.split(":")
    kind = parts[0].lower()

    if kind == "bimodal":
        if len(parts) != 4:
            raise ValueError("bimodal format: bimodal:<mice_frac>:<mice_size>:<ele_size>")
        mice_frac = float(parts[1])
        mice_size = int(parts[2])
        ele_size = int(parts[3])
        return ("bimodal", {"mice_frac": mice_frac, "mice_size": mice_size, "ele_size": ele_size})

    if kind == "pareto":
        if len(parts) != 4:
            raise ValueError("pareto format: pareto:<min_size>:<alpha>:<max_size>")
        return (
            "pareto",
            {
                "min_size": int(parts[1]),
                "alpha": float(parts[2]),
                "max_size": int(parts[3]),
            },
        )

    if kind == "lognormal":
        if len(parts) != 5:
            raise ValueError("lognormal format: lognormal:<mu>:<sigma>:<scale>:<max_size>")
        return (
            "lognormal",
            {
                "mu": float(parts[1]),
                "sigma": float(parts[2]),
                "scale": int(parts[3]),
                "max_size": int(parts[4]),
            },
        )

    if kind == "exponential":
        if len(parts) != 3:
            raise ValueError("exponential format: exponential:<mean_size>:<max_size>")
        return (
            "exponential",
            {
                "mean_size": int(parts[1]),
                "max_size": int(parts[2]),
            },
        )

    if kind == "heavytail":
        # heavytail:<sigma>:<min_size>:<max_size>
        if len(parts) != 4:
            raise ValueError("heavytail format: heavytail:<sigma>:<min_size>:<max_size>")
        sigma = float(parts[1])
        min_size = int(parts[2])
        max_size = int(parts[3])
        if sigma <= 0.0:
            raise ValueError("heavytail sigma must be > 0")
        if min_size <= 0 or max_size <= 0 or max_size < min_size:
            raise ValueError("heavytail bounds must satisfy 0 < min_size <= max_size")
        return ("heavytail", {"sigma": sigma, "min_size": min_size, "max_size": max_size})

    raise ValueError("Unknown size_dist. Supported: fixed, bimodal, pareto, lognormal, exponential, heavytail")


def sample_flow_size(kind, params):
    if kind == "fixed":
        return params["size"]
    if kind == "bimodal":
        return params["mice_size"] if random() < params["mice_frac"] else params["ele_size"]
    if kind == "pareto":
        x = int(params["min_size"] * paretovariate(params["alpha"]))
        return max(1, min(x, params["max_size"]))
    if kind == "lognormal":
        x = int(params["scale"] * lognormvariate(params["mu"], params["sigma"]))
        return max(1, min(x, params["max_size"]))
    if kind == "heavytail":
        x = int(params["min_size"] * lognormvariate(0.0, params["sigma"]))
        return max(params["min_size"], min(x, params["max_size"]))
    x = int(expovariate(1.0 / params["mean_size"]))
    return max(1, min(x, params["max_size"]))


if len(sys.argv) not in (8, 9):
    print("Usage: python gen_serial_alltoall.py <filename> <nodes> <conns> <groupsize> <flowsize> <extrastarttime> <randseed> [size_dist]")
    sys.exit()
filename = sys.argv[1]
nodes = int(sys.argv[2])
conns = int(sys.argv[3])
groupsize = int(sys.argv[4])
flowsize = int(sys.argv[5])
extrastarttime = float(sys.argv[6])
randseed = int(sys.argv[7])
size_dist_spec = sys.argv[8] if len(sys.argv) == 9 else "fixed"
dist_kind, dist_params = parse_size_dist(size_dist_spec, flowsize)

if conns % groupsize != 0:
    print("conns must be a multiple of groupsize\n");
    sys.exit()

print("Nodes: ", nodes)
print("Connections: ", conns)
print("All-to-all group size: ", groupsize)
print("Flowsize: ", flowsize, "bytes")
print("SizeDist: ", size_dist_spec)
print("ExtraStartTime: ", extrastarttime, "us")
print("Random Seed ", randseed)

f = open(filename, "w")
print("Nodes", nodes, file=f)
print("Connections", conns*(groupsize-1), file=f)
print("Triggers", conns*(groupsize-2), file=f)

srcs = []
dsts = []
groups = conns // groupsize;

print("Groups ", groups)


for n in range(nodes):
    srcs.append(n)
if randseed != 0:
    seed(randseed)
shuffle(srcs)

id = 0
trig_id = 1
for group in range(groups):
    print("group: ", group)
    groupsrcs = []
    for n in range(groupsize):
        groupsrcs.append(srcs[group * groupsize + n])

    print(groupsrcs)
    for s in range(groupsize):
        for d in range(1, groupsize):
            id += 1
            dst = (s+d)%groupsize
            out = str(groupsrcs[s]) + "->" + str(groupsrcs[dst]) + " id " + str(id)
            if d == 1:
                extra = randint(0, int(extrastarttime * 1000000))
                out = out + " start " + str(extra)
            else:
                out = out + " trigger " + str(trig_id)
                trig_id += 1
            out = out + " size " + str(sample_flow_size(dist_kind, dist_params))
            if d != groupsize - 1:
                out = out + " send_done_trigger " + str(trig_id)
            print(out, file=f)
            print(groupsrcs[s], "->", groupsrcs[dst])
for t in range(1, trig_id):
    out = "trigger id " + str(t) + " oneshot"
    print(out, file=f)

f.close()
