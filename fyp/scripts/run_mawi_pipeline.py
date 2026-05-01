#!/usr/bin/env python3
"""
Run MAWI ingest workflow from dump text to top-K sink split files.

Workflow:
1) Parse MAWI dump text
2) Split into top-K destination-prefix sink files
3) Optional sink flow-distribution grid plot
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path
from typing import List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-file",
        default="fyp/dataset/mawi/200803180000.dump.txt",
        help="MAWI dump text input (default: %(default)s)",
    )
    parser.add_argument(
        "--split-dir",
        default="fyp/dataset/mawi/mawi_sinks_top8_prefix16",
        help="Output directory for split sink files (default: %(default)s)",
    )
    parser.add_argument(
        "--prefix-len",
        type=int,
        default=16,
        help="Destination prefix length for grouping (default: %(default)s)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=8,
        help="Top K destination prefixes to keep (default: %(default)s)",
    )
    parser.add_argument(
        "--max-lines",
        type=int,
        default=0,
        help="Maximum input lines to process (0 means all)",
    )
    parser.add_argument(
        "--skip-plots",
        action="store_true",
        help="Skip sink flow-distribution plotting",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without running",
    )
    return parser.parse_args()


def run_step(cmd: List[str], cwd: Path, dry_run: bool) -> None:
    print(f"\n>> {shlex.join(cmd)}")
    if dry_run:
        return
    subprocess.run(cmd, cwd=str(cwd), check=True)


def convert_sink_tables_to_int(
    py: str,
    scripts_dir: Path,
    dc_root: Path,
    split_dir: Path,
    dry_run: bool,
) -> None:
    sink_files = sorted(split_dir.glob("*.txt"))
    if not sink_files:
        raise FileNotFoundError(f"No sink split files found in {split_dir}")

    print(f"\nConverting {len(sink_files)} MAWI sink file(s) to INT-style logs")
    for idx, sink_file in enumerate(sink_files, start=1):
        tmp_out = sink_file.with_suffix(".tmp_int")
        cmd = [
            py,
            str(scripts_dir / "imc_txt_to_cache_log.py"),
            str(sink_file),
            "--output",
            str(tmp_out),
        ]
        run_step(cmd, dc_root, dry_run)
        if not dry_run:
            tmp_out.replace(sink_file)
            print(f"  [{idx}/{len(sink_files)}] INT-style: {sink_file.name}")


def main() -> None:
    args = parse_args()
    scripts_dir = Path(__file__).resolve().parent
    dc_root = scripts_dir.parent
    py = sys.executable

    split_dir = Path(args.split_dir)

    print("MAWI workflow configuration")
    print(f"  input file:      {args.input_file}")
    print(f"  split dir:       {split_dir}")
    print(f"  prefix len:      {args.prefix_len}")
    print(f"  top-k:           {args.top_k}")
    print(f"  dry run:         {args.dry_run}")

    split_cmd = [
        py,
        str(scripts_dir / "split_mawi_dump_top8.py"),
        args.input_file,
        "--output-dir",
        str(split_dir),
        "--prefix-len",
        str(args.prefix_len),
        "--top-k",
        str(args.top_k),
        "--file-prefix",
        "mawi_sink",
    ]
    if args.max_lines > 0:
        split_cmd += ["--max-lines", str(args.max_lines)]
    run_step(split_cmd, dc_root, args.dry_run)

    if not args.skip_plots:
        plot_out = Path("fyp/results/mawi/flow_size/plots")
        plot_cmd = [
            py,
            str(scripts_dir / "plot_sink_flow_distributions.py"),
            "--split-dir",
            str(split_dir),
            "--out-dir",
            str(plot_out),
            "--prefix",
            split_dir.name,
            "--cols",
            "4",
        ]
        run_step(plot_cmd, dc_root, args.dry_run)

    # 3) Convert split sink tables to synthetic INT-style logs in-place.
    convert_sink_tables_to_int(py, scripts_dir, dc_root, split_dir, args.dry_run)

    print("\nWorkflow finished.")


if __name__ == "__main__":
    main()
