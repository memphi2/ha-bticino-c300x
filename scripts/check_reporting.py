#!/usr/bin/env python3
"""Shared failure reporting for the scripts/ validation gates."""

from __future__ import annotations

import sys


def report_failures(failures: list[str], success_message: str | None = None) -> int:
    """Write FAIL lines to stderr and return the gate's exit code.

    Passing a success message prints it when there are no failures; gates
    with multi-line success output pass None and print it themselves.
    """

    if failures:
        for failure in failures:
            sys.stderr.write(f"FAIL: {failure}\n")
        return 1
    if success_message is not None:
        sys.stdout.write(f"{success_message}\n")
    return 0
