#!/usr/bin/env python3
"""
Schedule experiments.txt entries into parallel waves.

Two entries conflict if they share the same (protocol, cm_family):
  - "cm_family" is the dataset name with trailing numeric suffixes and "_n" stripped,
    so incast_heavytail_burst_1, incast_heavytail_burst_8, incast_heavytail_burst_n
    all map to "incast_heavytail_burst" and cannot run in the same wave.

Output: one wave per line, each line is space-separated 1-based entry indices.
With --commands, prints the actual bash commands to run in waves.

Usage:
  python3 fyp/scripts/schedule_experiments.py
  python3 fyp/scripts/schedule_experiments.py --commands
  python3 fyp/scripts/schedule_experiments.py fyp/experiments/experiments.txt --commands
"""

import re
import sys
import argparse


def cm_family(dataset: str) -> str:
    """Strip trailing _n or _<digits> to get the connection-matrix family name."""
    name = re.sub(r"_n$", "", dataset)
    name = re.sub(r"_\d+$", "", name)
    return name


def parse_entries(path: str) -> list[tuple[int, str, str, str]]:
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) != 3:
                continue
            protocol, dataset, context = parts
            idx = len(entries) + 1
            entries.append((idx, protocol, dataset, context))
    return entries


def schedule(entries: list[tuple[int, str, str, str]]) -> list[list[int]]:
    """
    Greedy graph-colouring: assign each entry to the earliest wave where
    no conflict exists. Two entries conflict when (protocol, cm_family) match.
    O(n^2) — fine for small experiment lists.
    """
    waves: list[list[int]] = []
    wave_keys: list[set[tuple[str, str]]] = []

    for idx, protocol, dataset, _context in entries:
        key = (protocol, cm_family(dataset))
        placed = False
        for i, keys_in_wave in enumerate(wave_keys):
            if key not in keys_in_wave:
                waves[i].append(idx)
                keys_in_wave.add(key)
                placed = True
                break
        if not placed:
            waves.append([idx])
            wave_keys.append({key})

    return waves


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("experiments_file", nargs="?",
                    default="fyp/experiments/experiments.txt")
    ap.add_argument("--commands", action="store_true",
                    help="Print bash commands instead of index lists")
    args = ap.parse_args()

    entries = parse_entries(args.experiments_file)
    if not entries:
        print("No entries found.", file=sys.stderr)
        sys.exit(1)

    waves = schedule(entries)

    if not args.commands:
        for i, wave in enumerate(waves, 1):
            print(f"wave {i}: {wave}")
        return

    runner = "bash fyp/scripts/run_experiments.sh"
    for i, wave in enumerate(waves, 1):
        print(f"# Wave {i}")
        for idx in wave:
            _, protocol, dataset, context = entries[idx - 1]
            print(f"{idx}: {protocol}  {dataset}  {context}") 
        for idx in wave:
            _, protocol, dataset, context = entries[idx - 1]
            print(f"{runner} --entry {idx} &")
        print("wait")
        print()


if __name__ == "__main__":
    main()
