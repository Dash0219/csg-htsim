"""
Plot per-sink flow-size distributions from split IMC sink datasets.

Input files are expected to be split table files from split_imc_by_sink.py,
for example:
    dash_dataset/imc/univ2/univ2_sinks_top8_prefix16/univ2_sink_41.177.0.0_16.txt

Output:
    1) <prefix>.png : one bar-chart subplot per sink file

Each subplot shows flow size (packets per flow) vs frequency, using shared
power-of-two bins across sinks for direct visual comparison.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import math
import os
import re
from collections import defaultdict
from glob import glob
from pathlib import Path
from typing import Dict, List, Sequence, Tuple


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--split-dir",
        default="dash_dataset/imc/univ2/univ2_sinks_top8_prefix16",
        help="Directory containing sink split files (default: %(default)s).",
    )
    parser.add_argument(
        "--pattern",
        default="*.txt",
        help="Glob pattern for sink files (default: %(default)s).",
    )
    parser.add_argument(
        "--out-dir",
        default="",
        help=(
            "Output directory for figures "
            "(default: dash_results/imc/<dataset>/flow_size/plots inferred from --split-dir)."
        ),
    )
    parser.add_argument(
        "--prefix",
        default="sink_flow_size",
        help="Output file prefix (default: %(default)s).",
    )
    parser.add_argument("--show", action="store_true", help="Show plots interactively.")
    parser.add_argument(
        "--cols",
        type=int,
        default=4,
        help="Grid column count for sink subplots (default: %(default)s).",
    )
    parser.add_argument(
        "--max-sinks",
        type=int,
        default=0,
        help="Maximum sink files to plot (0 means all).",
    )
    parser.add_argument(
        "--sort-by",
        choices=["rows", "flows", "name"],
        default="rows",
        help="How to order sink subplots (default: %(default)s).",
    )
    return parser.parse_args()


def infer_imc_dataset(split_dir: Path) -> str:
    parts = [p.lower() for p in split_dir.parts]
    if "univ1" in parts:
        return "univ1"
    if "univ2" in parts:
        return "univ2"
    return "univ2"


def sniff_delimiter(path: Path) -> str:
    with path.open("r", encoding="utf-8", newline="") as f:
        header = f.readline()
    if "\t" in header:
        return "\t"
    if "," in header:
        return ","
    return "\t"


def flow_key(row: Dict[str, str]) -> Tuple[str, str, str, str, str]:
    return (
        (row.get("src_ip") or "").strip(),
        (row.get("dst_ip") or "").strip(),
        (row.get("l4_proto") or "").strip(),
        (row.get("src_port") or "").strip(),
        (row.get("dst_port") or "").strip(),
    )


def flow_record_counts(path: Path) -> Tuple[List[int], int]:
    # IMC/MAWI sink splits are now INT logs; keep legacy table parsing for compatibility.
    with path.open("r", encoding="utf-8", newline="") as f:
        first = f.readline().lstrip()
    if first.startswith("INT flow="):
        return flow_record_counts_int(path)

    return flow_record_counts_table(path)


def flow_record_counts_int(path: Path) -> Tuple[List[int], int]:
    counts = defaultdict(int)
    row_count = 0
    header_re = re.compile(r"INT flow=(\d+) seq=(\d+) hops=(\d+)")

    with path.open("r", encoding="utf-8", newline="") as f:
        for line in f:
            m = header_re.search(line)
            if not m:
                continue
            flow_id = int(m.group(1))
            counts[flow_id] += 1
            row_count += 1

    return list(counts.values()), row_count


def flow_record_counts_table(path: Path) -> Tuple[List[int], int]:
    counts = defaultdict(int)
    row_count = 0

    delimiter = sniff_delimiter(path)
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        for row in reader:
            k = flow_key(row)
            if not k[0] and not k[1]:
                continue
            counts[k] += 1
            row_count += 1

    return list(counts.values()), row_count


def build_pow2_bins(max_val: int) -> List[int]:
    bins = [1]
    while bins[-1] <= max_val:
        bins.append(bins[-1] * 2)
    return bins


def binned_frequency(values: Sequence[int], bins: Sequence[int]) -> List[int]:
    freq = [0] * (len(bins) - 1)
    for v in values:
        idx = bisect.bisect_right(bins, v) - 1
        idx = max(0, min(idx, len(freq) - 1))
        freq[idx] += 1
    return freq


def bin_labels(bins: Sequence[int]) -> List[str]:
    labels = []
    for i in range(len(bins) - 1):
        lo = bins[i]
        hi = bins[i + 1] - 1
        labels.append(str(lo) if lo == hi else f"{lo}-{hi}")
    return labels


def sink_name_from_file(path: Path) -> str:
    name = path.stem
    if name.startswith("sink_"):
        return name[len("sink_"):]
    return name


def plot_grid(
    sink_data: List[Tuple[Path, List[int], int]],
    out_dir: str,
    prefix: str,
    cols: int,
    show: bool,
) -> str:
    try:
        import matplotlib
        if not show:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        raise RuntimeError("matplotlib is required. Install with: pip install matplotlib")

    os.makedirs(out_dir, exist_ok=True)

    global_max = max(max(vals) for _, vals, _ in sink_data if vals)
    bins = build_pow2_bins(global_max)
    labels = bin_labels(bins)
    x = list(range(len(labels)))

    n = len(sink_data)
    cols = max(1, cols)
    rows = int(math.ceil(n / cols))

    fig, axs = plt.subplots(rows, cols, figsize=(4.2 * cols, 2.9 * rows), squeeze=False)

    colors = [
        "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b",
        "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    ]

    for i, (path, vals, row_count) in enumerate(sink_data):
        r = i // cols
        c = i % cols
        ax = axs[r][c]

        freq = binned_frequency(vals, bins)
        sink_name = sink_name_from_file(path)
        color = colors[i % len(colors)]
        ax.bar(x, freq, color=color, alpha=0.9)
        ax.set_title(f"{sink_name} | rows={row_count:,} flows={len(vals):,}", fontsize=9)
        ax.grid(True, axis="y", alpha=0.25)
        ax.set_ylabel("# flows")
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7)
        ax.set_xlabel("Flow size bin (packets/flow)")

    for j in range(n, rows * cols):
        r = j // cols
        c = j % cols
        axs[r][c].axis("off")

    fig.suptitle("Flow size over frequency per sink split", y=0.99)
    fig.tight_layout(rect=[0, 0, 1, 0.97])

    out_path = os.path.join(out_dir, f"{prefix}.png")
    fig.savefig(out_path, dpi=160)
    if show:
        plt.show()
    return out_path


def main() -> None:
    args = parse_args()
    split_dir = Path(args.split_dir)
    out_dir = args.out_dir or f"dash_results/imc/{infer_imc_dataset(split_dir)}/flow_size/plots"
    files = [Path(p) for p in glob(str(split_dir / args.pattern)) if Path(p).is_file()]
    files.sort(key=lambda p: p.name)

    if not files:
        raise FileNotFoundError(f"No sink files found in {split_dir} with pattern {args.pattern}")

    sink_data: List[Tuple[Path, List[int], int]] = []
    print("=== Loading sink flow distributions ===")
    for path in files:
        vals, row_count = flow_record_counts(path)
        sink_data.append((path, vals, row_count))
        max_flow = max(vals) if vals else 0
        print(
            f"{path.name:<36} rows={row_count:>10,} flows={len(vals):>10,} max_flow_size={max_flow:>8,}"
        )

    if args.sort_by == "rows":
        sink_data.sort(key=lambda x: x[2], reverse=True)
    elif args.sort_by == "flows":
        sink_data.sort(key=lambda x: len(x[1]), reverse=True)
    else:
        sink_data.sort(key=lambda x: x[0].name)

    if args.max_sinks > 0:
        sink_data = sink_data[: args.max_sinks]

    out_path = plot_grid(
        sink_data=sink_data,
        out_dir=out_dir,
        prefix=args.prefix,
        cols=args.cols,
        show=args.show,
    )

    print("\nSaved figure:")
    print(f"  {out_path}")


if __name__ == "__main__":
    main()
