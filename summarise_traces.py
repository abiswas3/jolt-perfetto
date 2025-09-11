#!/usr/bin/env python3
"""
summarise_traces.py

Command-line tool to summarise slices across multiple Perfetto trace JSON files under a given parent slice.

The script aggregates total duration and occurrences per slice name for each trace
and prints a table comparing all traces. Supports up to 7 traces for display.

Usage:
    python summarise_traces.py TRACE1 TRACE2 [TRACE3 ...] -p "Parent Slice Name" [-s SORT_OPTION]

Example:
    python summarise_traces.py trace1.json trace2.json trace3.json -p "Stage 3 sumchecks" -s time_1

Options:
    TRACE1, TRACE2, ...       Paths to Perfetto trace JSON files.
    -p, --parent              Parent slice name to analyze.
    -s, --sort                Sort option for table (linear, time_1, time_2, ...). Default: linear
"""

import argparse

from helpers import compare_multiple, print_nice


def main():
    """
    Entry point for the summarise_traces CLI.

    Parses command-line arguments, computes the aggregated slice stats for the specified
    parent slice across multiple trace files, and prints a nicely formatted table.

    Sorting options:
        - linear: preserves the order of first occurrence in the first trace.
        - time_X: sorts by total time in trace X (1-indexed) descending.
    """
    parser = argparse.ArgumentParser(
        description="Summarise slices in multiple Perfetto trace files under a parent slice."
    )
    parser.add_argument(
        "trace_files",
        nargs="+",
        help="Paths to the Perfetto JSON trace files to summarise (2 or more).",
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

    trace_files = args.trace_files
    parent_name = args.parent
    sort_option = args.sort

    # Compute aggregated comparison across multiple traces
    comparison_dict = compare_multiple(trace_files, parent_name)

    # Print nicely
    print_nice(comparison_dict, trace_files, sort_option=sort_option)


if __name__ == "__main__":
    main()
