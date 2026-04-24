"""
Convert IMC packet-table text into synthetic INT-style log records.

The existing cache simulator expects lines like:
  INT flow=<id> seq=<n> hops=1
    [0] sw=<id> type=1 qs=0 ts=<picoseconds> txbytes=<bytes> pktid=<id>

IMC packet captures do not include full per-hop paths, so this converter
builds a single-hop synthetic path where:
  - flow id is based on 5-tuple (src,dst,proto,sport,dport)
  - sw id is a stable integer assigned per source node

Input is the text produced by convert_imc_pcap_to_txt.py.
"""

from __future__ import annotations

import argparse
import csv
from glob import glob
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Sequence, Tuple


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input_path",
        help="Input IMC txt file or directory containing txt shards.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output synthetic INT log path.",
    )
    parser.add_argument(
        "--pattern",
        default="*_pt*.txt",
        help="Glob pattern when input_path is a directory (default: %(default)s).",
    )
    parser.add_argument(
        "--source-column",
        default="src_ip",
        help="Source node column in IMC txt (default: %(default)s).",
    )
    parser.add_argument(
        "--sink-column",
        default="dst_ip",
        help="Sink node column in IMC txt (default: %(default)s).",
    )
    parser.add_argument(
        "--proto-column",
        default="l4_proto",
        help="Protocol column in IMC txt (default: %(default)s).",
    )
    parser.add_argument(
        "--sport-column",
        default="src_port",
        help="Source-port column in IMC txt (default: %(default)s).",
    )
    parser.add_argument(
        "--dport-column",
        default="dst_port",
        help="Destination-port column in IMC txt (default: %(default)s).",
    )
    parser.add_argument(
        "--timestamp-column",
        default="timestamp",
        help="Timestamp column in seconds (default: %(default)s).",
    )
    parser.add_argument(
        "--length-column",
        default="wirelen",
        help="Packet length column (default: %(default)s).",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=0,
        help="Maximum rows to convert (0 means all rows).",
    )
    return parser.parse_args()


def sniff_delimiter(path: Path) -> str:
    with path.open("r", encoding="utf-8", newline="") as f:
        header = f.readline()
    if "\t" in header:
        return "\t"
    if "," in header:
        return ","
    return "\t"


def resolve_inputs(input_path: Path, pattern: str) -> List[Path]:
    if input_path.is_file():
        return [input_path]
    if not input_path.is_dir():
        raise FileNotFoundError(f"Input path does not exist: {input_path}")
    files = [Path(p) for p in glob(str(input_path / pattern)) if Path(p).is_file()]
    files.sort(key=lambda p: p.name)
    if not files:
        raise FileNotFoundError(f"No matching files under {input_path} with pattern {pattern}")
    return files


def parse_rows(files: Sequence[Path]) -> Iterator[Tuple[Path, Dict[str, str]]]:
    for path in files:
        delimiter = sniff_delimiter(path)
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            for row in reader:
                yield path, row


def to_picoseconds(ts_text: str) -> int:
    if not ts_text:
        return 0
    try:
        return int(round(float(ts_text) * 1_000_000_000_000))
    except ValueError:
        return 0


def to_int(text: str, default: int = 0) -> int:
    if not text:
        return default
    try:
        return int(text)
    except ValueError:
        return default


def main() -> None:
    args = parse_args()
    input_path = Path(args.input_path)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    files = resolve_inputs(input_path, args.pattern)

    source_to_sw: Dict[str, int] = {}
    flow_to_id: Dict[Tuple[str, str, str, str, str], int] = {}
    flow_seq: Dict[int, int] = {}

    total_rows = 0
    written_rows = 0
    skipped_rows = 0

    with output_path.open("w", encoding="utf-8", newline="") as out:
        for src_file, row in parse_rows(files):
            total_rows += 1
            if args.max_rows > 0 and written_rows >= args.max_rows:
                break

            src = (row.get(args.source_column) or "").strip()
            dst = (row.get(args.sink_column) or "").strip()
            proto = (row.get(args.proto_column) or "").strip()
            sport = (row.get(args.sport_column) or "").strip()
            dport = (row.get(args.dport_column) or "").strip()

            if not src:
                skipped_rows += 1
                continue

            flow_key = (src, dst, proto, sport, dport)
            flow_id = flow_to_id.setdefault(flow_key, len(flow_to_id) + 1)
            sw_id = source_to_sw.setdefault(src, len(source_to_sw))
            seq = flow_seq.get(flow_id, 0) + 1
            flow_seq[flow_id] = seq

            ts_ps = to_picoseconds((row.get(args.timestamp_column) or "").strip())
            txbytes = to_int((row.get(args.length_column) or "").strip(), default=0)
            pktid = written_rows + 1

            out.write(f"INT flow={flow_id} seq={seq} hops=1\n")
            out.write(
                f"  [0] sw={sw_id} type=1 qs=0 ts={ts_ps} txbytes={txbytes} pktid={pktid}\n"
            )
            written_rows += 1

    print("Done.")
    print(f"  Input files:         {len(files):,}")
    print(f"  Source rows seen:    {total_rows:,}")
    print(f"  Rows written:        {written_rows:,}")
    print(f"  Rows skipped:        {skipped_rows:,}")
    print(f"  Unique sources:      {len(source_to_sw):,}")
    print(f"  Unique flow keys:    {len(flow_to_id):,}")
    print(f"  Output log:          {output_path}")


if __name__ == "__main__":
    main()
