# cython: language_level=3

cpdef tuple simulate_records(object records, object cache):
    cdef long total = 0
    cdef long hits = 0
    cdef long necessary_forwards = 0
    cdef long new_route_forwards = 0
    cdef long route_change_forwards = 0
    cdef long redundant_forwards = 0
    cdef long evictions = 0

    cdef object collector_seen_paths = {}
    cdef object r
    cdef object flow
    cdef tuple path
    cdef long ts
    cdef object seen_paths
    cdef tuple out
    cdef bint hit
    cdef bint evicted

    for r in records:
        flow = r['flow']
        path = tuple(r['sw'])
        ts = r['ts'][-1] if r['ts'] else 0
        total += 1

        out = cache.lookup_and_update(flow, path, ts)
        hit = bool(out[0])
        evicted = bool(out[1])

        if evicted:
            evictions += 1

        if hit:
            hits += 1
            continue

        seen_paths = collector_seen_paths.get(flow)
        if seen_paths is None:
            necessary_forwards += 1
            new_route_forwards += 1
            collector_seen_paths[flow] = {path}
        elif path not in seen_paths:
            necessary_forwards += 1
            route_change_forwards += 1
            seen_paths.add(path)
        else:
            redundant_forwards += 1

    return (
        total,
        hits,
        necessary_forwards,
        new_route_forwards,
        route_change_forwards,
        redundant_forwards,
        evictions,
    )


cpdef tuple simulate_source_seen_records(object records, object cache):
    cdef long total = 0
    cdef long hits = 0
    cdef long necessary_forwards = 0
    cdef long new_route_forwards = 0
    cdef long route_change_forwards = 0
    cdef long redundant_forwards = 0
    cdef long evictions = 0

    cdef object collector_seen_paths = {}
    cdef object r
    cdef object source
    cdef object route_sig
    cdef long ts
    cdef object seen_paths
    cdef tuple out
    cdef bint hit
    cdef bint evicted

    for r in records:
        source = r['source']
        route_sig = r['route_sig']
        ts = r['ts_ps']
        total += 1

        out = cache.lookup_and_update(source, route_sig, ts)
        hit = bool(out[0])
        evicted = bool(out[1])

        if evicted:
            evictions += 1

        if hit:
            hits += 1
            continue

        seen_paths = collector_seen_paths.get(source)
        if seen_paths is None:
            necessary_forwards += 1
            new_route_forwards += 1
            collector_seen_paths[source] = {route_sig}
        elif route_sig not in seen_paths:
            necessary_forwards += 1
            route_change_forwards += 1
            seen_paths.add(route_sig)
        else:
            redundant_forwards += 1

    return (
        total,
        hits,
        necessary_forwards,
        new_route_forwards,
        route_change_forwards,
        redundant_forwards,
        evictions,
    )
