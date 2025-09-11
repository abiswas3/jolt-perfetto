from collections import OrderedDict
from pathlib import Path

import numpy as np
import pandas as pd
from perfetto.trace_processor import TraceProcessor


def print_nice(comparison_dict, trace_files, sort_option="linear", max_name_width=40):
    """
    Pretty-print a flat comparison dictionary with table-like formatting.

    Shows:
    name | total_time_s_<trace1> | total_time_s_<trace2> | diff_time_s | ratio_time_s

    Parameters
    ----------
    comparison_dict : dict
        Dictionary from compare_two(), keyed by slice name.
    trace_files : list of str
        Two trace file paths used for comparison. Used for headers.
    sort_option : str
        Sorting method: 'linear' (insertion order), 'diff', 'time_a', 'time_b'.
    max_name_width : int
        Maximum width of slice name column (longer names truncated with '...').
    """
    # ANSI color codes
    RED = "\033[91m"
    GREEN = "\033[92m"
    RESET = "\033[0m"

    if not comparison_dict:
        print("No slices to display.")
        return

    # Get headers from filenames
    name_a = Path(trace_files[0]).name
    name_b = Path(trace_files[1]).name
    total_keys = [
        k
        for k in next(iter(comparison_dict.values())).keys()
        if k.startswith("total_time_s_")
    ]

    # Compute column widths
    name_width = min(max(len(name) for name in comparison_dict.keys()), max_name_width)
    width_1 = (
        max(
            len(total_keys[0]),
            *(len(f"{v[total_keys[0]]:.6f}") for v in comparison_dict.values()),
        )
        + 2
    )
    width_2 = (
        max(
            len(total_keys[1]),
            *(len(f"{v[total_keys[1]]:.6f}") for v in comparison_dict.values()),
        )
        + 2
    )

    # Header
    header = (
        f"{'Name'.ljust(name_width)}  "
        f"{name_a.rjust(width_1)}  "
        f"{name_b.rjust(width_2)}  Diff(s)    Ratio"
    )
    print(header)
    print("-" * (len(header) + 2))

    # Decide sorting
    items = comparison_dict.items()
    if sort_option == "diff":
        items = sorted(items, key=lambda x: x[1]["diff_time_s"], reverse=True)
    elif sort_option == "time_a":
        items = sorted(items, key=lambda x: x[1][total_keys[0]], reverse=True)
    elif sort_option == "time_b":
        items = sorted(items, key=lambda x: x[1][total_keys[1]], reverse=True)

    # Print rows
    for name, stats in items:
        display_name = (
            name if len(name) <= max_name_width else name[: max_name_width - 3] + "..."
        )
        total_a = stats[total_keys[0]]
        total_b = stats[total_keys[1]]
        diff = stats["diff_time_s"]
        ratio = stats["ratio_time_s"]

        # Safe ratio string
        ratio_str = (
            f"{ratio:.2f}" if ratio is not None and not (ratio != ratio) else "NaN"
        )

        # Color diff
        if diff > 0:
            diff_str = f"{GREEN}{diff:10.6f}{RESET}"
        elif diff < 0:
            diff_str = f"{RED}{diff:10.6f}{RESET}"
        else:
            diff_str = f"{diff:10.6f}"

        line = (
            f"{display_name.ljust(name_width)}  "
            f"{total_a:>{width_1}.6f}  "
            f"{total_b:>{width_2}.6f}  "
            f"{diff_str}  "
            f"{ratio_str:>6}"
        )
        print(line)
    print()


def compute_breakdown(trace_file, parent_name):
    """
    Compute a flat breakdown of slices under a specific parent slice
    from a Perfetto trace file (no depth levels).

    This function extracts all slices that occur fully within the time span
    of a given parent slice (`parent_name`) and aggregates them by slice name.
    It produces both the raw slice DataFrame (with one row per occurrence) and
    an aggregated breakdown (with one row per slice name).

    Steps:
    1. Query the trace to get all slices whose [ts, ts+dur] interval lies fully
       inside the parent slice's [ts, ts+dur].
    2. Aggregate slices by `name`, computing:
         - total_time_s: sum of durations (converted to seconds).
         - occurrences: number of times the slice appears.
         - first_ts: earliest timestamp at which the slice appeared.
    3. Order the breakdown by `first_ts` so slices are listed chronologically
       by their first occurrence.
    4. Drop the helper column `first_ts` before returning.

    Parameters
    ----------
    trace_file : str
        Path to the Perfetto trace JSON file.
    parent_name : str
        Name of the parent slice whose children should be analyzed.

    Returns
    -------
    tuple
        (df_raw, df_breakdown)
        - df_raw : pd.DataFrame
            Raw slice data, one row per occurrence with columns: [id, name, ts, dur].
        - df_breakdown : pd.DataFrame
            Aggregated per-slice statistics with columns:
              * name: slice name
              * total_time_s: float, total duration in seconds
              * occurrences: int, number of times this slice appeared
            Rows are ordered by first occurrence in time.

    Example
    -------
    >>> df_raw, df_breakdown = compute_breakdown("trace-small.json", "Stage 3 sumchecks")
    >>> print(df_breakdown)
                name  total_time_s  occurrences
    0   bind_parallel      0.123456            5
    1     bind_serial      0.045678            2
    2  finalize_stage      0.010111            1
    """
    # Step 1: Query all slices fully inside the parent
    query = f"""
    WITH parent AS (
        SELECT ts, ts + dur AS end_ts
        FROM slice
        WHERE name = '{parent_name}'
    )
    SELECT s.id, s.name, s.ts, s.dur
    FROM slice s
    JOIN parent p ON s.ts >= p.ts AND (s.ts + s.dur) <= p.end_ts
    ORDER BY s.ts;
    """

    with TraceProcessor(trace_file) as tp:
        df_raw = tp.query(query).as_pandas_dataframe()

    if df_raw.empty:
        return pd.DataFrame(columns=["name", "total_time_s", "occurrences"])

    # Aggregate by name only (no depth)
    df_breakdown = (
        df_raw.groupby("name")
        .agg(
            total_time_s=("dur", lambda x: x.sum() / 1e9),
            occurrences=("dur", "count"),
            first_ts=("ts", "min"),  # earliest time this slice appears
        )
        .reset_index()
        .sort_values("first_ts")  # order by first occurrence
        .drop(columns=["first_ts"])  # optional: drop helper column
        .reset_index(drop=True)
    )

    return df_raw, df_breakdown


def compare_two(trace_files, parent_name):
    """
    Compare slice breakdowns for two Perfetto trace files under a given parent slice.

    This function extracts all slices that occur within the time window of
    a specified parent slice (`parent_name`) from two different Perfetto trace files,
    then aggregates their total duration and occurrences per slice name. Finally, it
    merges the two results and computes differences and ratios for comparison.

    Steps:
    1. Calls `compute_breakdown` on each trace file to get per-slice statistics.
       Each breakdown includes:
         - total_time_s: total duration in seconds of the slice name
         - occurrences: number of times the slice appears
         - first_ts: timestamp of first occurrence (used internally)
    2. Merges the two DataFrames on `name` (slice name).
    3. Computes:
         - diff_time_s = total_time_s_<trace2> - total_time_s_<trace1>
         - diff_occurrences = occurrences_<trace2> - occurrences_<trace1>
         - ratio_time_s = total_time_s_<trace2> / total_time_s_<trace1> (NaN if denominator=0)
    4. Returns an OrderedDict keyed by slice name, preserving chronological order from the first trace.

    Parameters
    ----------
    trace_files : list of str
        Exactly two Perfetto trace JSON file paths [trace1, trace2].
    parent_name : str
        The parent slice name whose children should be analyzed.

    Returns
    -------
    OrderedDict
        Dictionary keyed by slice name:
        {
          "slice_name": {
              "total_time_s_<trace1>": float,
              "total_time_s_<trace2>": float,
              "occurrences_<trace1>": int,
              "occurrences_<trace2>": int,
              "diff_time_s": float,
              "diff_occurrences": int,
              "ratio_time_s": float or NaN
          },
          ...
        }

    Example
    -------
    >>> trace_files = ["trace-small.json", "trace-large.json"]
    >>> parent_name = "Stage 3 sumchecks"
    >>> comparison = compare_two(trace_files, parent_name)
    >>> import pprint; pprint.pprint(comparison, indent=2)
    {
      "bind_parallel": {
        "total_time_s_trace-small": 0.123,
        "total_time_s_trace-large": 0.250,
        "occurrences_trace-small": 5,
        "occurrences_trace-large": 8,
        "diff_time_s": 0.127,
        "diff_occurrences": 3,
        "ratio_time_s": 2.032
      },
      "bind_serial": {
        "total_time_s_trace-small": 0.045,
        "total_time_s_trace-large": 0.030,
        "occurrences_trace-small": 2,
        "occurrences_trace-large": 1,
        "diff_time_s": -0.015,
        "diff_occurrences": -1,
        "ratio_time_s": 0.667
      }
    }
    """
    assert len(trace_files) == 2

    # Compute breakdowns (returns linear/raw and aggregated)
    df_a_linear, df_a = compute_breakdown(trace_files[0], parent_name)
    df_b_linear, df_b = compute_breakdown(trace_files[1], parent_name)

    # Map slice names to first occurrence index in first trace
    name_order = {
        name: i for i, name in enumerate(df_a_linear["name"].drop_duplicates())
    }

    # Merge aggregated data
    df_compare = pd.merge(
        df_a, df_b, on="name", how="outer", suffixes=("_a", "_b")
    ).fillna(0)

    # Add order column based on first trace
    df_compare["order"] = df_compare["name"].map(
        lambda x: name_order.get(x, float("inf"))
    )

    # Sort by first occurrence in first trace
    df_compare = (
        df_compare.sort_values("order", na_position="last")
        .drop(columns="order")
        .reset_index(drop=True)
    )

    # Compute differences and ratios
    df_compare["diff_time_s"] = (
        df_compare["total_time_s_b"] - df_compare["total_time_s_a"]
    )
    df_compare["diff_occurrences"] = (
        df_compare["occurrences_b"] - df_compare["occurrences_a"]
    )
    df_compare["ratio_time_s"] = np.where(
        df_compare["total_time_s_a"] == 0,
        np.nan,
        df_compare["total_time_s_b"] / df_compare["total_time_s_a"],
    )

    # Use trace file base names for dynamic field names
    name_a = Path(trace_files[0]).stem
    name_b = Path(trace_files[1]).stem

    comparison_dict = OrderedDict(
        (
            row["name"],
            {
                f"total_time_s_{name_a}": row["total_time_s_a"],
                f"total_time_s_{name_b}": row["total_time_s_b"],
                f"occurrences_{name_a}": int(row["occurrences_a"]),
                f"occurrences_{name_b}": int(row["occurrences_b"]),
                "diff_time_s": row["diff_time_s"],
                "diff_occurrences": int(row["diff_occurrences"]),
                "ratio_time_s": row["ratio_time_s"],
            },
        )
        for _, row in df_compare.iterrows()
    )

    return comparison_dict
