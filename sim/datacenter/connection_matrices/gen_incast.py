#!/usr/bin/env python

# Generate an incast traffic matrix.
# python gen_incast.py <filename> <nodes> <conns> <flowsize> <extrastarttime> <randseed> [size_dist]
# Parameters:
# <nodes>   number of nodes in the topology
# <conns>    number of active connections
# <flowsize>   default fixed size (bytes), used when size_dist omitted
# <extrastarttime>   How long in microseconds to space the start times over (start time will be random in between 0 and this time).  Can be a float.
# <randseed>   Seed for random number generator, or set to 0 for random seed
# [size_dist] optional flow-size distribution spec:
#   fixed
#   bimodal:<mice_frac>:<mice_size>:<ele_size>
#   pareto:<min_size>:<alpha>:<max_size>
#   lognormal:<mu>:<sigma>:<scale>:<max_size>
#   exponential:<mean_size>:<max_size>
#   heavytail:<sigma>:<min_size>:<max_size>
#     lognormal(mu=0, sigma) scaled so median ~ min_size; sigma controls concentration.
#     Higher sigma -> fewer flows carry most packets (more like real datacenter traffic).

import os
import sys
from random import seed, shuffle, randint, random, paretovariate, lognormvariate, expovariate


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
        if not (0.0 <= mice_frac <= 1.0):
            raise ValueError("bimodal mice_frac must be in [0,1]")
        if mice_size <= 0 or ele_size <= 0:
            raise ValueError("bimodal sizes must be > 0")
        return ("bimodal", {
            "mice_frac": mice_frac,
            "mice_size": mice_size,
            "ele_size": ele_size,
        })

    if kind == "pareto":
        if len(parts) != 4:
            raise ValueError("pareto format: pareto:<min_size>:<alpha>:<max_size>")
        min_size = int(parts[1])
        alpha = float(parts[2])
        max_size = int(parts[3])
        if min_size <= 0 or max_size <= 0 or max_size < min_size:
            raise ValueError("pareto bounds must satisfy 0 < min_size <= max_size")
        if alpha <= 0.0:
            raise ValueError("pareto alpha must be > 0")
        return ("pareto", {
            "min_size": min_size,
            "alpha": alpha,
            "max_size": max_size,
        })

    if kind == "lognormal":
        if len(parts) != 5:
            raise ValueError("lognormal format: lognormal:<mu>:<sigma>:<scale>:<max_size>")
        mu = float(parts[1])
        sigma = float(parts[2])
        scale = int(parts[3])
        max_size = int(parts[4])
        if sigma <= 0.0:
            raise ValueError("lognormal sigma must be > 0")
        if scale <= 0 or max_size <= 0 or max_size < scale:
            raise ValueError("lognormal bounds must satisfy 0 < scale <= max_size")
        return ("lognormal", {
            "mu": mu,
            "sigma": sigma,
            "scale": scale,
            "max_size": max_size,
        })

    if kind == "exponential":
        if len(parts) != 3:
            raise ValueError("exponential format: exponential:<mean_size>:<max_size>")
        mean_size = int(parts[1])
        max_size = int(parts[2])
        if mean_size <= 0 or max_size <= 0 or max_size < mean_size:
            raise ValueError("exponential bounds must satisfy 0 < mean_size <= max_size")
        return ("exponential", {
            "mean_size": mean_size,
            "max_size": max_size,
        })

    if kind == "heavytail":
        # heavytail:<sigma>:<min_size>:<max_size>
        # Lognormal(mu=0, sigma) * min_size, clipped to [min_size, max_size].
        # sigma is the concentration parameter: higher -> fewer flows carry most bytes.
        # Typical real-world datacenter traffic: sigma ~ 1.5 to 2.5.
        if len(parts) != 4:
            raise ValueError("heavytail format: heavytail:<sigma>:<min_size>:<max_size>")
        sigma = float(parts[1])
        min_size = int(parts[2])
        max_size = int(parts[3])
        if sigma <= 0.0:
            raise ValueError("heavytail sigma must be > 0")
        if min_size <= 0 or max_size <= 0 or max_size < min_size:
            raise ValueError("heavytail bounds must satisfy 0 < min_size <= max_size")
        return ("heavytail", {
            "sigma": sigma,
            "min_size": min_size,
            "max_size": max_size,
        })

    raise ValueError("Unknown size_dist. Supported: fixed, bimodal, pareto, lognormal, exponential, heavytail")


def sample_flow_size(kind, params):
    if kind == "fixed":
        return params["size"]

    if kind == "bimodal":
        if random() < params["mice_frac"]:
            return params["mice_size"]
        return params["ele_size"]

    if kind == "pareto":
        # Pareto with truncation at max_size.
        # Python's paretovariate(alpha) has xm=1 so scale by min_size.
        x = int(params["min_size"] * paretovariate(params["alpha"]))
        if x > params["max_size"]:
            x = params["max_size"]
        if x < 1:
            x = 1
        return x

    if kind == "lognormal":
        x = int(params["scale"] * lognormvariate(params["mu"], params["sigma"]))
        if x > params["max_size"]:
            x = params["max_size"]
        if x < 1:
            x = 1
        return x

    if kind == "heavytail":
        # Lognormal with mu=0, scaled by min_size so median == min_size.
        # sigma controls concentration: higher sigma -> heavier tail.
        x = int(params["min_size"] * lognormvariate(0.0, params["sigma"]))
        x = max(params["min_size"], min(x, params["max_size"]))
        return x

    # Exponential with truncation at max_size
    x = int(expovariate(1.0 / params["mean_size"]))
    if x > params["max_size"]:
        x = params["max_size"]
    if x < 1:
        x = 1
    return x


if len(sys.argv) not in (7, 8):
    print("Usage: python gen_incast.py <filename> <nodes> <conns> <flowsize> <extrastarttime> <randseed> [size_dist]")
    print("  size_dist examples:")
    print("    fixed")
    print("    bimodal:0.8:64000:10000000")
    print("    pareto:32000:1.3:20000000")
    print("    lognormal:0.0:1.2:1460:50000000")
    print("    exponential:200000:50000000")
    print("    heavytail:1.5:9000:50000000   (sigma=1.5, median=9000B, max=50MB)")
    sys.exit()

filename = sys.argv[1]
nodes = int(sys.argv[2])
conns = int(sys.argv[3])
flowsize = int(sys.argv[4])
extrastarttime = float(sys.argv[5])
randseed = int(sys.argv[6])
size_dist_spec = sys.argv[7] if len(sys.argv) == 8 else "fixed"

dist_kind, dist_params = parse_size_dist(size_dist_spec, flowsize)

print("Nodes: ", nodes)
print("Connections: ", conns)
print("Default Flowsize: ", flowsize, "bytes")
print("SizeDist: ", size_dist_spec)
print("ExtraStartTime: ", extrastarttime, "us")
print("Random Seed ", randseed)

f = open(filename, "w")
print("Nodes", nodes, file=f)
print("Connections", conns, file=f)

srcs = []
for n in range(1, nodes):
    srcs.append(n)

if conns > len(srcs):
    raise ValueError("conns must be <= nodes-1 for incast source selection")

if randseed != 0:
    seed(randseed)
shuffle(srcs)

dst = "0"

for n in range(conns):
    extra = randint(0, int(extrastarttime * 1000000))
    sampled_size = sample_flow_size(dist_kind, dist_params)
    out = str(srcs[n]) + "->" + str(dst) + " id " + str(n + 1) + " start " + str(extra) + " size " + str(sampled_size)
    print(out, file=f)

f.close()
