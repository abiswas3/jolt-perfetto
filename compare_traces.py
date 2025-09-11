#!/usr/bin/env python3
"""
compare_traces.py

Command-line tool to compare slices in two Perfetto trace JSON files under a given parent slice.

The script extracts all slices that occur within the time window of a specified parent slice,
aggregates their total duration and occurrences per slice name, and prints a comparison table
with differences and ratios.

Usage:
    python compare_traces.py TRACE1 TRACE2 -p "Parent Slice Name" [-s SORT_OPTION]

Example:
    python compare_traces.py trace-small.json trace-large.json -p "Stage 3 sumchecks" -s diff

Options:
    TRACE1, TRACE2          Paths to the two Perfetto trace JSON files.
    -p, --parent            Parent slice name to analyze.
    -s, --sort              Sort option for table (linear, diff, time_a, time_b). Default: linear
"""

import argparse
from pathlib import Path

from helpers import compare_two, print_nice


def main():
    """
    Entry point for the compare_traces CLI.

    Parses command-line arguments, computes the comparison dictionary for the specified
    parent slice across two trace files, and prints a nicely formatted table.

    Sorting options:
        - linear: preserves the order of first occurrence in the first trace.
        - diff: sorts by difference in total time (trace B - trace A) descending.
        - time_a: sorts by total time in first trace descending.
        - time_b: sorts by total time in second trace descending.
    """
    parser = argparse.ArgumentParser(
        description="Compare slices in two Perfetto trace files under a parent slice."
    )
    parser.add_argument(
        "trace_files",
        nargs=2,
        help="Paths to the two Perfetto JSON trace files to compare.",
    )
    parser.add_argument(
        "--parent",
        "-p",
        required=True,
        help="Parent slice name whose children will be analyzed.",
    )
    parser.add_argument(
        "--sort",
        "-s",
        choices=["linear", "diff", "time_a", "time_b"],
        default="linear",
        help="Sort order for printing the table.",
    )

    args = parser.parse_args()

    trace_files = args.trace_files
    parent_name = args.parent
    sort_option = args.sort

    # Compute comparison
    comparison_dict = compare_two(trace_files, parent_name)

    # Print nicely
    print_nice(comparison_dict, trace_files, sort_option=sort_option)


if __name__ == "__main__":
    main()
