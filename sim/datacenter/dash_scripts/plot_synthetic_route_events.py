"""
Plot synthetic cache-sim route event metrics.

This script is intentionally scoped to synthetic cache-sim CSV outputs generated
by cache_sim.py sweep runs. It shows both collector-needed route event rates
(new-route and route-change) and cache-sensitive rates (overall forwarding and
redundant forwarding) across cache capacities.

Usage:
  python3 dash_scripts/plot_synthetic_route_events.py \
        dash_results/synthetic/cache_sim/route_changes/results_synthetic_incast_mono.csv \
      --out-dir dash_results/synthetic/cache_sim/route_changes/plots

  python3 dash_scripts/plot_synthetic_route_events.py \
        dash_results/synthetic/cache_sim/route_changes/results_synthetic_*.csv \
      --out-dir dash_results/synthetic/cache_sim/route_changes/plots --show

    # Use built-in synthetic defaults (incast_mono, a2a_mono, and paired
    # distribution variants with incast_/a2a_ prefixes)
    python3 dash_scripts/plot_synthetic_route_events.py --use-defaults --out-dir dash_results/synthetic/cache_sim/route_changes/plots
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, TypedDict


class EventRow(TypedDict):
    cache: str
    capacity: float
    new_rate: float
    chg_rate: float
    fwd_rate: float
    red_rate: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "csv_files",
        nargs="*",
        help="Synthetic cache-sim CSV file(s) from cache_sim.py --sweep",
    )
    parser.add_argument(
            "--out-dir",
            default="dash_results/synthetic/cache_sim/route_changes/plots",
        help="Directory for generated PNGs (default: %(default)s)",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Show figures interactively",
    )
    parser.add_argument(
        "--policies",
        default="",
        help="Comma-separated policy names to include (default: include all bounded policies)",
    )
    parser.add_argument(
        "--use-defaults",
        action="store_true",
        help="Plot the default synthetic route-change CSV set under dash_results/synthetic/cache_sim/route_changes",
    )
    return parser.parse_args()


def default_synthetic_csvs() -> List[Path]:
    root = Path("dash_results/synthetic/cache_sim/route_changes")
    return sorted(root.glob("results_synthetic_*.csv"))


def infer_workload_name(path: Path) -> str:
    stem = path.stem
    if stem.startswith("results_synthetic_"):
        return stem[len("results_synthetic_"):]
    return stem


def load_rows(path: Path) -> List[EventRow]:
    rows: List[EventRow] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {
            "cache",
            "capacity",
            "total",
            "new_route_forwards",
            "route_change_forwards",
            "forward_rate",
            "redundancy_rate",
        }
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing columns in {path}: {sorted(missing)}")

        for row in reader:
            cap = float(row["capacity"])
            if cap <= 0:
                continue
            total = int(row["total"])
            if total <= 0:
                continue
            new_fw = int(row["new_route_forwards"])
            chg_fw = int(row["route_change_forwards"])
            rows.append(
                {
                    "cache": row["cache"],
                    "capacity": cap,
                    "new_rate": 100.0 * new_fw / total,
                    "chg_rate": 100.0 * chg_fw / total,
                    "fwd_rate": 100.0 * float(row["forward_rate"]),
                    "red_rate": 100.0 * float(row["redundancy_rate"]),
                }
            )
    return rows


def group_by_policy(rows: List[EventRow]) -> Dict[str, List[EventRow]]:
    grouped: Dict[str, List[EventRow]] = defaultdict(list)
    for row in rows:
        grouped[str(row["cache"])].append(row)
    for key in grouped:
        grouped[key].sort(key=lambda r: r["capacity"])
    return dict(grouped)


def pick_policies(grouped: Dict[str, List[EventRow]], include: str) -> List[str]:
    if include.strip():
        desired = [p.strip() for p in include.split(",") if p.strip()]
        return [p for p in desired if p in grouped]
    return sorted(grouped.keys())


def plot_one(csv_path: Path, out_dir: Path, show: bool, include: str) -> None:
    try:
        import matplotlib
        if not show:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib is required: pip install matplotlib", file=sys.stderr)
        raise

    rows = load_rows(csv_path)
    if not rows:
        print(f"No bounded rows found in {csv_path}", file=sys.stderr)
        return

    grouped = group_by_policy(rows)
    policies = pick_policies(grouped, include)
    if not policies:
        print(f"No matching policies found in {csv_path}", file=sys.stderr)
        return

    workload = infer_workload_name(csv_path)

    fig, (ax1, ax2, ax3, ax4) = plt.subplots(1, 4, figsize=(20, 4.8), sharex=True)

    for policy in policies:
        series = grouped[policy]
        xs = [r["capacity"] for r in series]
        new_ys = [r["new_rate"] for r in series]
        chg_ys = [r["chg_rate"] for r in series]
        fwd_ys = [r["fwd_rate"] for r in series]
        red_ys = [r["red_rate"] for r in series]
        ax1.plot(xs, new_ys, marker="o", linewidth=1.8, label=policy)
        ax2.plot(xs, chg_ys, marker="o", linewidth=1.8, label=policy)
        ax3.plot(xs, fwd_ys, marker="o", linewidth=1.8, label=policy)
        ax4.plot(xs, red_ys, marker="o", linewidth=1.8, label=policy)

    for ax in (ax1, ax2, ax3, ax4):
        ax.set_xscale("log", base=2)
        ax.set_xlabel("Cache capacity (flow slots)")
        ax.grid(True, which="both", alpha=0.25)

    ax1.set_ylabel("New-route forward rate (% of packets)")
    ax1.set_title("New-route forwards")
    ax2.set_ylabel("Route-change forward rate (% of packets)")
    ax2.set_title("Route-change forwards")
    ax3.set_ylabel("Forward rate (% of packets)")
    ax3.set_title("All forwards")
    ax4.set_ylabel("Redundancy rate (% of forwards)")
    ax4.set_title("Redundant forwards")

    handles, labels = ax4.get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=4, fontsize=8, frameon=False)
    fig.suptitle(f"Synthetic workload: {workload}")
    fig.tight_layout(rect=(0, 0, 1, 0.92))

    out_file = out_dir / f"synthetic_route_events_{workload}.png"
    fig.savefig(out_file, dpi=150)
    print(f"Saved {out_file}")

    if show:
        plt.show()



def ensure_synthetic_inputs(paths: List[Path]) -> None:
    bad = [p for p in paths if "synthetic" not in p.as_posix()]
    if bad:
        joined = ", ".join(str(p) for p in bad)
        raise ValueError(
            "This plotter is synthetic-only. Non-synthetic input detected: "
            f"{joined}"
        )



def main() -> None:
    args = parse_args()
    csv_paths = [Path(p) for p in args.csv_files]
    if args.use_defaults:
        csv_paths.extend(default_synthetic_csvs())
    if not csv_paths:
        raise ValueError("No CSV inputs provided. Pass files or use --use-defaults.")

    # De-duplicate while preserving order.
    deduped = []
    seen = set()
    for p in csv_paths:
        s = str(p)
        if s in seen:
            continue
        seen.add(s)
        deduped.append(p)
    csv_paths = deduped

    ensure_synthetic_inputs(csv_paths)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for path in csv_paths:
        if not path.exists():
            print(f"Missing input CSV: {path}", file=sys.stderr)
            continue
        plot_one(path, out_dir, args.show, args.policies)


if __name__ == "__main__":
    main()
