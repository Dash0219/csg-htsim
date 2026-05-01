#!/usr/bin/env python3
"""Average per-seed cache sim CSVs across runs and compute 95% CI for key metrics."""
import argparse
import collections
import csv
import math
import pathlib
import statistics

METRICS_CI = ["suppression_rate", "redundancy_rate", "forward_rate"]


def main():
    ap = argparse.ArgumentParser(
        description="Aggregate cache sim CSVs from multiple seeds into mean + CI95."
    )
    ap.add_argument("--inputs", nargs="+", required=True,
                    help="Per-seed result CSVs (one per run)")
    ap.add_argument("--output", required=True,
                    help="Output CSV path (mean + ci95 columns)")
    args = ap.parse_args()

    rows_by_key = collections.defaultdict(list)
    fieldnames = None
    insertion_order = []

    for path in args.inputs:
        p = pathlib.Path(path)
        if not p.exists():
            print(f"WARN: input not found, skipping: {path}")
            continue
        with open(p, newline="") as f:
            reader = csv.DictReader(f)
            if fieldnames is None:
                fieldnames = list(reader.fieldnames)
            for row in reader:
                key = (row["cache"], row["capacity"])
                if key not in rows_by_key:
                    insertion_order.append(key)
                rows_by_key[key].append(row)

    if fieldnames is None:
        print("ERROR: no valid input files found")
        raise SystemExit(1)

    ci_fields = [f"{m}_ci95" for m in METRICS_CI]
    out_fields = fieldnames + ci_fields

    pathlib.Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=out_fields)
        w.writeheader()
        for key in insertion_order:
            rows = rows_by_key[key]
            out = {}
            for field in fieldnames:
                vals = []
                for r in rows:
                    v = r.get(field, "")
                    if v not in ("", None):
                        try:
                            vals.append(float(v))
                        except ValueError:
                            pass
                if vals:
                    try:
                        out[field] = statistics.mean(vals)
                    except Exception:
                        out[field] = rows[0].get(field, "")
                else:
                    out[field] = rows[0].get(field, "")
            for m in METRICS_CI:
                vals = []
                for r in rows:
                    v = r.get(m, "")
                    if v not in ("", None):
                        try:
                            vals.append(float(v))
                        except ValueError:
                            pass
                n = len(vals)
                ci = 1.96 * statistics.stdev(vals) / math.sqrt(n) if n > 1 else 0.0
                out[f"{m}_ci95"] = ci
            out["cache"] = key[0]
            out["capacity"] = key[1]
            w.writerow(out)

    print(f"Wrote {len(insertion_order)} rows to {args.output}")


if __name__ == "__main__":
    main()
