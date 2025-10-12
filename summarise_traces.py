#!/usr/bin/env python3
"""
summarise_traces.py

Command-line tool to summarise slices across multiple Perfetto trace JSON files under a given parent slice.

The script aggregates total duration and occurrences per slice name for each trace
and prints a table comparing all traces. Supports up to 7 traces for display.

Usage:
    python summarise_traces.py /path/to/trace_dir -p "Parent Slice Name" [-s SORT_OPTION]

Example:
    python summarise_traces.py ./traces -p "Stage 3 sumchecks" -s time_1

Options:
    TRACE_DIR                Path to directory containing Perfetto JSON trace files.
    -p, --parent             Parent slice name to analyze.
    -s, --sort               Sort option for table (linear, time_1, time_2, ...). Default: linear
"""

import argparse
import glob
import os

from helpers import compare_multiple, print_nice
from stats import print_with_stats


def main():
    """
    Entry point for the summarise_traces CLI.

    Parses command-line arguments, computes the aggregated slice stats for the specified
    parent slice across multiple trace files in a directory, and prints a nicely formatted table.

    Sorting options:
        - linear: preserves the order of first occurrence in the first trace.
        - time_X: sorts by total time in trace X (1-indexed) descending.
    """
    parser = argparse.ArgumentParser(
        description="Summarise slices in multiple Perfetto trace files under a parent slice."
    )
    parser.add_argument(
        "trace_dir",
        help="Path to a directory containing the Perfetto JSON trace files to summarise.",
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
        default="linear",
        help="Sort order for printing the table (linear or time_X for trace X).",
    )

    args = parser.parse_args()

    # Gather all JSON files from the given directory
    trace_dir = args.trace_dir
    trace_files = sorted(glob.glob(os.path.join(trace_dir, "*.json")))

    if len(trace_files) < 2:
        print("Error: The directory must contain at least two JSON trace files.")
        return

    parent_name = args.parent
    sort_option = args.sort

    # Compute aggregated comparison across multiple traces
    comparison_dict = compare_multiple(trace_files, parent_name)

    # Print nicely
    print_with_stats(comparison_dict, trace_files, sort_option=sort_option)


if __name__ == "__main__":
    main()
