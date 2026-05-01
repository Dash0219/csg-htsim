"""
Run IMC ingest workflow for one dataset (e.g., uni1/uni2).

Workflow order (no cache-sim stage here):
1) PCAP shards -> TXT shards
2) Split TXT shards by destination prefix and keep top-K sinks
3) Optional grid plot over split outputs

This workflow intentionally avoids creating or processing one huge merged file.

Examples:
    python3 fyp/dash_scripts/run_imc_pipeline.py uni1
    python3 fyp/dash_scripts/run_imc_pipeline.py uni2 --ip-prefix-len 24
"""

from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", help="Dataset name, e.g. uni1 or uni2.")
    parser.add_argument(
        "--data-root",
        default="fyp/dash_dataset/imc",
        help="Dataset parent directory (default: %(default)s).",
    )
    parser.add_argument(
        "--trace-dir",
        default="",
        help="Optional explicit trace directory. Default auto-detects *_trace_pcap then *_trace under nested/flat layouts.",
    )
    parser.add_argument(
        "--txt-dir",
        default="",
        help="Optional explicit output directory for converted TXT shards.",
    )
    parser.add_argument(
        "--split-dir",
        default="",
        help="Optional explicit output directory for prefix split files.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=8,
        help="Keep only top-K destination prefixes by row count (default: %(default)s).",
    )
    parser.add_argument(
        "--trace-pattern",
        default="",
        help="PCAP shard glob inside <dataset>_trace (default: <dataset>_pt*).",
    )
    parser.add_argument(
        "--txt-pattern",
        default="",
        help="TXT shard glob for split stage (default: <dataset>_pt*.txt).",
    )
    parser.add_argument(
        "--ip-prefix-len",
        type=int,
        default=16,
        help="Prefix length for sink grouping (default: %(default)s).",
    )
    parser.add_argument(
        "--plot-cols",
        type=int,
        default=4,
        help="Grid columns for sink distribution plots (default: %(default)s).",
    )
    parser.add_argument(
        "--max-packets",
        type=int,
        default=0,
        help="Limit packets per pcap shard during conversion (0 means all).",
    )
    parser.add_argument(
        "--max-split-rows",
        type=int,
        default=0,
        help="Limit rows processed during split stage (0 means all).",
    )
    parser.add_argument(
        "--skip-plots",
        action="store_true",
        help="Skip sink-grid plotting for split outputs.",
    )
    parser.add_argument(
        "--keep-txt-dir",
        action="store_true",
        help="Keep intermediate converted TXT shard directory (<dataset>_trace_txt).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without executing.",
    )
    return parser.parse_args()


def run_step(cmd: List[str], cwd: Path, dry_run: bool) -> None:
    pretty = shlex.join(cmd)
    print(f"\n>> {pretty}")
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

    print(f"\nConverting {len(sink_files)} sink split file(s) to INT-style logs")
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

    data_root = Path(args.data_root)
    nested_dataset_dir = data_root / args.dataset
    flat_dataset_dir = data_root
    dataset_dir = nested_dataset_dir if nested_dataset_dir.exists() else flat_dataset_dir

    if args.trace_dir:
        trace_dir = Path(args.trace_dir)
    else:
        trace_candidates = [
            dataset_dir / f"{args.dataset}_trace_pcap",
            dataset_dir / f"{args.dataset}_trace",
            data_root / f"{args.dataset}_trace_pcap",
            data_root / f"{args.dataset}_trace",
        ]
        trace_dir = next((p for p in trace_candidates if p.exists() and p.is_dir()), trace_candidates[0])

    trace_pattern = args.trace_pattern or f"{args.dataset}_pt*"
    txt_pattern = args.txt_pattern or f"{args.dataset}_pt*.txt"

    txt_dir = Path(args.txt_dir) if args.txt_dir else dataset_dir / f"{args.dataset}_trace_txt"
    split_dir = (
        Path(args.split_dir)
        if args.split_dir
        else dataset_dir / f"{args.dataset}_sinks_top{args.top_k}_prefix{args.ip_prefix_len}"
    )

    if not trace_dir.exists() or not trace_dir.is_dir():
        raise FileNotFoundError(f"Trace directory not found: {trace_dir}")

    print("IMC workflow configuration")
    print(f"  dataset:         {args.dataset}")
    print(f"  dataset dir:     {dataset_dir}")
    print(f"  trace dir:       {trace_dir}")
    print(f"  trace pattern:   {trace_pattern}")
    print(f"  txt dir:         {txt_dir}")
    print(f"  txt pattern:     {txt_pattern}")
    print(f"  split dir:       {split_dir}")
    print(f"  top-k:           {args.top_k}")
    print(f"  prefix len:      {args.ip_prefix_len}")
    print(f"  dry run:         {args.dry_run}")

    # 1) PCAP -> TXT table
    cmd = [
        py,
        str(scripts_dir / "convert_imc_pcap_to_txt.py"),
        str(trace_dir),
        "--pattern",
        trace_pattern,
        "--output-dir",
        str(txt_dir),
    ]
    if args.max_packets > 0:
        cmd += ["--max-packets", str(args.max_packets)]
    run_step(cmd, dc_root, args.dry_run)

    # 2) Split by destination prefix directly from TXT shards
    if split_dir.exists() and not args.dry_run:
        shutil.rmtree(split_dir)
    cmd = [
        py,
        str(scripts_dir / "split_imc_by_sink.py"),
        str(txt_dir),
        "--pattern",
        txt_pattern,
        "--output-dir",
        str(split_dir),
        "--ip-prefix-len",
        str(args.ip_prefix_len),
        "--top-k",
        str(args.top_k),
        "--file-prefix",
        f"{args.dataset}_sink",
    ]
    if args.max_split_rows > 0:
        cmd += ["--max-rows", str(args.max_split_rows)]
    run_step(cmd, dc_root, args.dry_run)

    # 3) Plot sink-grid distributions
    if not args.skip_plots:
        split_name = split_dir.name
        plot_prefix = split_name
        cmd = [
            py,
            str(scripts_dir / "plot_sink_flow_distributions.py"),
            "--split-dir",
            str(split_dir),
            "--out-dir",
            str(Path("dash_results") / "imc" / args.dataset / "flow_size" / "plots"),
            "--prefix",
            plot_prefix,
            "--cols",
            str(args.plot_cols),
        ]
        run_step(cmd, dc_root, args.dry_run)

    # 4) Convert split sink tables to INT-style logs in-place.
    convert_sink_tables_to_int(py, scripts_dir, dc_root, split_dir, args.dry_run)

    # 5) Remove intermediate pcap->table conversion directory unless requested.
    if not args.keep_txt_dir:
        txt_abs = txt_dir.resolve()
        split_abs = split_dir.resolve()
        trace_abs = trace_dir.resolve()
        if txt_abs != split_abs and txt_abs != trace_abs and txt_dir.exists():
            if args.dry_run:
                print(f"\nWould remove intermediate TXT dir: {txt_dir}")
            else:
                shutil.rmtree(txt_dir)
                print(f"\nRemoved intermediate TXT dir: {txt_dir}")
        else:
            print(f"\nSkipping TXT-dir cleanup for safety: {txt_dir}")

    print("\nWorkflow finished.")


if __name__ == "__main__":
    main()
