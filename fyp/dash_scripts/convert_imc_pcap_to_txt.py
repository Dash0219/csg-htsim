"""
convert_imc_pcap_to_txt.py - Convert IMC 2010 PCAP shards into text TSV files.

This script reads classic PCAP files directly (no external libraries required)
and exports one packet per line with common L2/L3/L4 fields.

Examples:
  # Convert one shard into a .txt next to the input file
        python3 fyp/dash_scripts/convert_imc_pcap_to_txt.py fyp/dash_dataset/imc/univ2/univ2_trace_pcap/univ2_pt1

    # Convert all shards in a dataset folder into an output folder
  python3 fyp/dash_scripts/convert_imc_pcap_to_txt.py \
                        fyp/dash_dataset/imc/univ2/univ2_trace_pcap --output-dir fyp/dash_dataset/imc/univ2/univ2_trace_txt

  # Convert directory and also write one merged TSV file
  python3 fyp/dash_scripts/convert_imc_pcap_to_txt.py \
                        fyp/dash_dataset/imc/univ2/univ2_trace_pcap \
                        --output-dir fyp/dash_dataset/imc/univ2/univ2_trace_txt \
                        --merged-output fyp/dash_dataset/imc/univ2/univ2_trace_all.txt
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import struct
from dataclasses import dataclass
from glob import glob
from pathlib import Path
from typing import BinaryIO, Dict, Iterable, List, Optional, Tuple


PCAP_GLOBAL_HEADER_LEN = 24
PCAP_PACKET_HEADER_LEN = 16

MAGIC_TO_ENDIAN_AND_SCALE = {
    b"\xd4\xc3\xb2\xa1": ("<", 1_000_000),
    b"\xa1\xb2\xc3\xd4": (">", 1_000_000),
    b"\x4d\x3c\xb2\xa1": ("<", 1_000_000_000),
    b"\xa1\xb2\x3c\x4d": (">", 1_000_000_000),
}


@dataclass
class PcapHeaderInfo:
    endian: str
    ts_scale: int


@dataclass
class PacketRow:
    source_file: str
    packet_index: int
    ts_sec: int
    ts_frac: int
    timestamp: float
    caplen: int
    wirelen: int
    ethertype: str
    vlan_depth: int
    ip_version: str
    src_ip: str
    dst_ip: str
    l4_proto: str
    src_port: str
    dst_port: str

    def to_list(self) -> List[str]:
        return [
            self.source_file,
            str(self.packet_index),
            str(self.ts_sec),
            str(self.ts_frac),
            f"{self.timestamp:.9f}",
            str(self.caplen),
            str(self.wirelen),
            self.ethertype,
            str(self.vlan_depth),
            self.ip_version,
            self.src_ip,
            self.dst_ip,
            self.l4_proto,
            self.src_port,
            self.dst_port,
        ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input_path",
        help="Path to a pcap file or a directory of pcap shards.",
    )
    parser.add_argument(
        "--pattern",
        default="*_pt*",
        help="Glob pattern used when input_path is a directory (default: %(default)s).",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory for per-input .txt files when converting a directory.",
    )
    parser.add_argument(
        "--merged-output",
        default=None,
        help="Optional merged output TXT file containing all converted packets.",
    )
    parser.add_argument(
        "--delimiter",
        default="\t",
        help="Column delimiter in output text (default: TAB).",
    )
    parser.add_argument(
        "--max-packets",
        type=int,
        default=0,
        help="Maximum packets to export per input file (0 means no limit).",
    )
    parser.add_argument(
        "--skip-non-ip",
        action="store_true",
        help="Only export packets with IPv4 or IPv6 headers.",
    )
    return parser.parse_args()


def read_pcap_header(handle: BinaryIO) -> PcapHeaderInfo:
    header = handle.read(PCAP_GLOBAL_HEADER_LEN)
    if len(header) != PCAP_GLOBAL_HEADER_LEN:
        raise ValueError("File too short to be a valid PCAP capture")

    magic = header[:4]
    if magic not in MAGIC_TO_ENDIAN_AND_SCALE:
        raise ValueError(f"Unsupported PCAP magic bytes: {magic!r}")

    endian, ts_scale = MAGIC_TO_ENDIAN_AND_SCALE[magic]
    return PcapHeaderInfo(endian=endian, ts_scale=ts_scale)


def iter_pcap_packets(handle: BinaryIO, info: PcapHeaderInfo) -> Iterable[Tuple[int, int, int, int, bytes]]:
    packet_struct = struct.Struct(f"{info.endian}IIII")

    while True:
        packet_header = handle.read(PCAP_PACKET_HEADER_LEN)
        if not packet_header:
            break
        if len(packet_header) != PCAP_PACKET_HEADER_LEN:
            raise ValueError("Truncated packet header encountered")

        ts_sec, ts_frac, caplen, wirelen = packet_struct.unpack(packet_header)
        payload = handle.read(caplen)
        if len(payload) != caplen:
            raise ValueError("Truncated packet payload encountered")

        yield ts_sec, ts_frac, caplen, wirelen, payload


def mac_proto_name(proto_num: int) -> str:
    if proto_num == 0x0800:
        return "IPv4"
    if proto_num == 0x86DD:
        return "IPv6"
    if proto_num == 0x0806:
        return "ARP"
    return f"0x{proto_num:04x}"


def l4_proto_name(proto_num: int) -> str:
    mapping = {1: "ICMP", 6: "TCP", 17: "UDP", 58: "ICMPv6"}
    return mapping.get(proto_num, str(proto_num))


def parse_ethernet(payload: bytes) -> Dict[str, object]:
    out: Dict[str, object] = {
        "ethertype": "",
        "vlan_depth": 0,
        "ip_version": "",
        "src_ip": "",
        "dst_ip": "",
        "l4_proto": "",
        "src_port": "",
        "dst_port": "",
    }

    if len(payload) < 14:
        return out

    offset = 14
    ethertype = struct.unpack("!H", payload[12:14])[0]
    vlan_depth = 0

    # Handle single or stacked VLAN tags.
    while ethertype in (0x8100, 0x88A8, 0x9100):
        if len(payload) < offset + 4:
            out["ethertype"] = f"0x{ethertype:04x}"
            out["vlan_depth"] = vlan_depth
            return out
        vlan_depth += 1
        ethertype = struct.unpack("!H", payload[offset + 2:offset + 4])[0]
        offset += 4

    out["ethertype"] = mac_proto_name(ethertype)
    out["vlan_depth"] = vlan_depth

    if ethertype == 0x0800:
        parse_ipv4(payload, offset, out)
    elif ethertype == 0x86DD:
        parse_ipv6(payload, offset, out)

    return out


def parse_ipv4(payload: bytes, offset: int, out: Dict[str, object]) -> None:
    if len(payload) < offset + 20:
        return

    version_ihl = payload[offset]
    version = (version_ihl >> 4) & 0x0F
    ihl = (version_ihl & 0x0F) * 4
    if version != 4 or ihl < 20 or len(payload) < offset + ihl:
        return

    proto = payload[offset + 9]
    src_ip_raw = payload[offset + 12:offset + 16]
    dst_ip_raw = payload[offset + 16:offset + 20]

    out["ip_version"] = "IPv4"
    out["src_ip"] = str(ipaddress.IPv4Address(src_ip_raw))
    out["dst_ip"] = str(ipaddress.IPv4Address(dst_ip_raw))
    out["l4_proto"] = l4_proto_name(proto)

    l4_offset = offset + ihl
    if proto in (6, 17) and len(payload) >= l4_offset + 4:
        sport, dport = struct.unpack("!HH", payload[l4_offset:l4_offset + 4])
        out["src_port"] = str(sport)
        out["dst_port"] = str(dport)


def parse_ipv6(payload: bytes, offset: int, out: Dict[str, object]) -> None:
    if len(payload) < offset + 40:
        return

    version = (payload[offset] >> 4) & 0x0F
    if version != 6:
        return

    next_header = payload[offset + 6]
    src_ip_raw = payload[offset + 8:offset + 24]
    dst_ip_raw = payload[offset + 24:offset + 40]

    out["ip_version"] = "IPv6"
    out["src_ip"] = str(ipaddress.IPv6Address(src_ip_raw))
    out["dst_ip"] = str(ipaddress.IPv6Address(dst_ip_raw))
    out["l4_proto"] = l4_proto_name(next_header)

    l4_offset = offset + 40
    if next_header in (6, 17) and len(payload) >= l4_offset + 4:
        sport, dport = struct.unpack("!HH", payload[l4_offset:l4_offset + 4])
        out["src_port"] = str(sport)
        out["dst_port"] = str(dport)


def write_header_line(handle: BinaryIO, delimiter: str) -> None:
    cols = [
        "source_file",
        "packet_index",
        "ts_sec",
        "ts_frac",
        "timestamp",
        "caplen",
        "wirelen",
        "ethertype",
        "vlan_depth",
        "ip_version",
        "src_ip",
        "dst_ip",
        "l4_proto",
        "src_port",
        "dst_port",
    ]
    line = delimiter.join(cols) + "\n"
    handle.write(line.encode("utf-8"))


def convert_one_file(
    input_file: Path,
    output_file: Path,
    delimiter: str,
    max_packets: int,
    skip_non_ip: bool,
    merged_handle: Optional[BinaryIO],
) -> Tuple[int, int]:
    output_file.parent.mkdir(parents=True, exist_ok=True)

    packets_seen = 0
    rows_written = 0

    with input_file.open("rb") as f_in, output_file.open("wb") as f_out:
        info = read_pcap_header(f_in)
        write_header_line(f_out, delimiter)

        for idx, (ts_sec, ts_frac, caplen, wirelen, payload) in enumerate(iter_pcap_packets(f_in, info), start=1):
            if max_packets > 0 and idx > max_packets:
                break
            packets_seen += 1

            decoded = parse_ethernet(payload)
            if skip_non_ip and decoded["ip_version"] == "":
                continue

            timestamp = ts_sec + (ts_frac / info.ts_scale)
            row = PacketRow(
                source_file=input_file.name,
                packet_index=idx,
                ts_sec=ts_sec,
                ts_frac=ts_frac,
                timestamp=timestamp,
                caplen=caplen,
                wirelen=wirelen,
                ethertype=str(decoded["ethertype"]),
                vlan_depth=int(decoded["vlan_depth"]),
                ip_version=str(decoded["ip_version"]),
                src_ip=str(decoded["src_ip"]),
                dst_ip=str(decoded["dst_ip"]),
                l4_proto=str(decoded["l4_proto"]),
                src_port=str(decoded["src_port"]),
                dst_port=str(decoded["dst_port"]),
            )

            out_line = delimiter.join(row.to_list()) + "\n"
            encoded = out_line.encode("utf-8")
            f_out.write(encoded)
            if merged_handle is not None:
                merged_handle.write(encoded)
            rows_written += 1

    return packets_seen, rows_written


def resolve_inputs(path: Path, pattern: str) -> List[Path]:
    if path.is_file():
        if not looks_like_pcap(path):
            raise ValueError(f"Input file does not look like a PCAP capture: {path}")
        return [path]
    if not path.is_dir():
        raise FileNotFoundError(f"Input path does not exist: {path}")

    candidates = [Path(p) for p in glob(str(path / pattern))]
    files: List[Path] = []
    skipped: List[Path] = []
    for p in candidates:
        if not p.is_file():
            continue
        if looks_like_pcap(p):
            files.append(p)
        else:
            skipped.append(p)

    files.sort(key=lambda p: p.name)
    if not files:
        raise FileNotFoundError(f"No files found under {path} matching pattern: {pattern}")

    for p in skipped:
        print(f"Skipping non-PCAP file: {p}")

    return files


def looks_like_pcap(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            magic = f.read(4)
        return magic in MAGIC_TO_ENDIAN_AND_SCALE
    except OSError:
        return False


def output_for_input(input_file: Path, root_input: Path, output_dir: Optional[Path]) -> Path:
    if root_input.is_file():
        if output_dir is not None:
            return output_dir / f"{input_file.name}.txt"
        return input_file.with_suffix(input_file.suffix + ".txt")
    if output_dir is None:
        output_dir = root_input / "txt_exports"
    return output_dir / f"{input_file.name}.txt"


def main() -> None:
    args = parse_args()

    input_path = Path(args.input_path)
    output_dir = Path(args.output_dir) if args.output_dir else None
    files = resolve_inputs(input_path, args.pattern)

    merged_handle: Optional[BinaryIO] = None
    merged_path: Optional[Path] = None
    if args.merged_output:
        merged_path = Path(args.merged_output)
        merged_path.parent.mkdir(parents=True, exist_ok=True)
        merged_handle = merged_path.open("wb")
        write_header_line(merged_handle, args.delimiter)

    total_seen = 0
    total_written = 0

    try:
        for i, f in enumerate(files, start=1):
            out_file = output_for_input(f, input_path, output_dir)
            seen, written = convert_one_file(
                input_file=f,
                output_file=out_file,
                delimiter=args.delimiter,
                max_packets=args.max_packets,
                skip_non_ip=args.skip_non_ip,
                merged_handle=merged_handle,
            )
            total_seen += seen
            total_written += written
            print(f"[{i}/{len(files)}] {f.name}: packets_seen={seen:,}, rows_written={written:,} -> {out_file}")
    finally:
        if merged_handle is not None:
            merged_handle.close()

    print("\nDone.")
    print(f"  Input files:      {len(files):,}")
    print(f"  Packets seen:     {total_seen:,}")
    print(f"  Rows written:     {total_written:,}")
    if merged_path is not None:
        print(f"  Merged output:    {merged_path}")


if __name__ == "__main__":
    main()