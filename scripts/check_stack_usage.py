#!/usr/bin/env python3
"""Fail when native-agent stack frames exceed the configured budget."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

STATIC_STACK_QUALIFIERS = frozenset({"static"})


@dataclass(frozen=True)
class StackUsage:
    path: Path
    location: str
    function: str
    bytes_used: int


def parse_stack_qualifiers(raw: str) -> frozenset[str]:
    """Parse GCC stack-usage qualifiers."""

    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def parse_stack_usage_line(path: Path, line: str) -> StackUsage:
    """Parse one GCC .su line."""

    parts = line.rstrip("\n").split("\t")
    if len(parts) < 3:
        raise ValueError(f"{path}: unparsable stack-usage line: {line!r}")
    try:
        bytes_used = int(parts[1])
    except ValueError as exc:
        raise ValueError(f"{path}: invalid stack usage size: {line!r}") from exc
    qualifiers = parse_stack_qualifiers(parts[2])
    if qualifiers != STATIC_STACK_QUALIFIERS:
        raise ValueError(f"{path}: non-static stack usage: {line!r}")
    location = parts[0]
    function = location.rsplit(":", maxsplit=1)[-1]
    return StackUsage(path, location, function, bytes_used)


def collect_stack_usage(root: Path) -> list[StackUsage]:
    """Collect all stack usage records below a build directory."""

    records: list[StackUsage] = []
    for path in sorted(root.rglob("*.su")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(parse_stack_usage_line(path, line))
    return records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("build_dir", type=Path)
    parser.add_argument("--limit", type=int, default=16_384)
    args = parser.parse_args()

    try:
        records = collect_stack_usage(args.build_dir)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    if not records:
        raise SystemExit(f"no .su files found under {args.build_dir}")

    offenders = [record for record in records if record.bytes_used > args.limit]
    if offenders:
        for record in sorted(offenders, key=lambda item: item.bytes_used, reverse=True):
            sys.stdout.write(
                f"{record.path}: {record.function} uses {record.bytes_used} bytes "
                f"(limit {args.limit})\n"
            )
        return 1

    largest = max(records, key=lambda item: item.bytes_used)
    sys.stdout.write(
        f"Stack usage check passed: max {largest.bytes_used} bytes "
        f"in {largest.function} (limit {args.limit})\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
