#!/usr/bin/env python3
"""
Split MAWI tcpdump text into top-K destination-prefix sink shards.

Expected input resembles tcpdump text lines, for example:
  1206918000.123456 IP 1.2.3.4.1234 > 5.6.7.8.80: ... length 1500

Output files are tab-separated text with IMC-compatible columns:
  timestamp src_ip dst_ip l4_proto src_port dst_port wirelen
"""

from __future__ import annotations

import argparse
import csv
import ipaddress
import re
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

LINE_RE = re.compile(
    r"^\s*(?P<ts>(?:\d+(?:\.\d+)?)|(?:\d{1,2}:\d{2}:\d{2}(?:\.\d+)?))\s+"
    r"IP\s+(?P<src>[^\s>]+)\s+>\s+(?P<dst>[^:]+):.*?(?:\blength\s+(?P<len>\d+))?"
)

ENDPOINT_IPV4_RE = re.compile(
    r"^(?P<ip>\d{1,3}(?:\.\d{1,3}){3})(?:\.(?P<port>[A-Za-z0-9_-]+))?$"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_file", help="MAWI tcpdump text file")
    parser.add_argument("--output-dir", required=True, help="Directory for per-sink files")
    parser.add_argument("--prefix-len", type=int, default=16, help="IPv4 prefix length (default: %(default)s)")
    parser.add_argument("--top-k", type=int, default=8, help="Top K prefixes to keep (default: %(default)s)")
    parser.add_argument("--file-prefix", default="mawi_sink", help="Output file prefix (default: %(default)s)")
    parser.add_argument("--max-lines", type=int, default=0, help="Max input lines to read (0 means all)")
    return parser.parse_args()


def split_ip_port(token: str) -> Tuple[Optional[str], str]:
    token = token.strip().rstrip(":")
    if not token:
        return None, ""

    m = ENDPOINT_IPV4_RE.match(token)
    if not m:
        return None, ""

    ip_part = m.group("ip")
    try:
        ipaddress.IPv4Address(ip_part)
    except ValueError:
        return None, ""

    port_part = m.group("port") or ""
    return ip_part, port_part


def normalize_timestamp(ts_text: str) -> str:
    ts_text = ts_text.strip()
    if not ts_text:
        return "0"
    if ":" not in ts_text:
        return ts_text

    # Convert HH:MM:SS[.frac] to seconds-from-midnight for downstream tools.
    hh, mm, rest = ts_text.split(":", 2)
    sec = float(rest)
    total = int(hh) * 3600.0 + int(mm) * 60.0 + sec
    return f"{total:.6f}"


def dst_prefix(dst_ip: str, prefix_len: int) -> Optional[str]:
    try:
        addr = ipaddress.IPv4Address(dst_ip)
    except ValueError:
        return None
    net = ipaddress.ip_network(f"{addr}/{prefix_len}", strict=False)
    return f"{net.network_address}/{prefix_len}"


def parse_rows(path: Path, max_lines: int = 0) -> Iterator[Dict[str, str]]:
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for idx, line in enumerate(f, start=1):
            if max_lines > 0 and idx > max_lines:
                break
            m = LINE_RE.search(line)
            if not m:
                continue

            src_ip, src_port = split_ip_port(m.group("src") or "")
            dst_ip, dst_port = split_ip_port(m.group("dst") or "")
            if src_ip is None or dst_ip is None:
                continue

            yield {
                "timestamp": normalize_timestamp(m.group("ts") or "0"),
                "src_ip": src_ip,
                "dst_ip": dst_ip,
                "l4_proto": "tcp",
                "src_port": src_port,
                "dst_port": dst_port,
                "wirelen": m.group("len") or "0",
            }


def sanitize_prefix(prefix: str) -> str:
    return prefix.replace("/", "_").replace(":", "_")


def main() -> None:
    args = parse_args()
    input_file = Path(args.input_file)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    counts: Counter[str] = Counter()
    total_rows = 0
    for row in parse_rows(input_file, max_lines=args.max_lines):
        total_rows += 1
        pfx = dst_prefix(row["dst_ip"], args.prefix_len)
        if pfx is not None:
            counts[pfx] += 1

    if not counts:
        raise SystemExit("No parseable IPv4 rows found in MAWI dump")

    top_prefixes = [pfx for pfx, _ in counts.most_common(args.top_k)]
    top_set = set(top_prefixes)

    handles: Dict[str, object] = {}
    writers: Dict[str, csv.DictWriter] = {}
    fieldnames = ["timestamp", "src_ip", "dst_ip", "l4_proto", "src_port", "dst_port", "wirelen"]
    kept_rows = 0

    try:
        for row in parse_rows(input_file, max_lines=args.max_lines):
            pfx = dst_prefix(row["dst_ip"], args.prefix_len)
            if pfx is None or pfx not in top_set:
                continue
            if pfx not in writers:
                suffix = sanitize_prefix(pfx)
                out_path = output_dir / f"{args.file_prefix}_{suffix}.txt"
                fh = out_path.open("w", encoding="utf-8", newline="")
                w = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t")
                w.writeheader()
                handles[pfx] = fh
                writers[pfx] = w
            writers[pfx].writerow(row)
            kept_rows += 1
    finally:
        for fh in handles.values():
            fh.close()

    print("Done.")
    print(f"  Source rows parsed:  {total_rows:,}")
    print(f"  Rows kept (top-{args.top_k}): {kept_rows:,}")
    print(f"  Prefix length:       /{args.prefix_len}")
    print(f"  Output directory:    {output_dir}")
    print("  Top prefixes:")
    for pfx, cnt in counts.most_common(args.top_k):
        print(f"    {pfx}: {cnt:,}")


if __name__ == "__main__":
    main()
