import numpy as np
import pandas as pd
from perfetto.trace_processor import TraceProcessor


def print_nice(comparison_dict):
    """
    Pretty-print a flat comparison dictionary with table-like formatting.

    Shows:
    name | total_time_s_small | total_time_s_large | diff_time_s | ratio_time_s
    """
    # ANSI color codes
    RED = "\033[91m"
    GREEN = "\033[92m"
    RESET = "\033[0m"

    if not comparison_dict:
        print("No slices to display.")
        return

    # Compute max width for the name column
    name_width = max(len(name) for name in comparison_dict.keys())
    header = (
        f"{'Name'.ljust(name_width)}  TimeSmall(s)  TimeLarge(s)   Diff(s)    Ratio"
    )
    print(header)
    print("-" * (len(header) + 2))

    # Sort by diff descending
    for name, stats in sorted(
        comparison_dict.items(), key=lambda x: x[1]["diff_time_s"], reverse=True
    ):
        total_small = stats["total_time_s_small"]
        total_large = stats["total_time_s_large"]
        diff = stats["diff_time_s"]
        ratio = stats["ratio_time_s"]

        # Safe ratio string
        ratio_str = (
            f"{ratio:.2f}" if ratio is not None and not (ratio != ratio) else "NaN"
        )

        # Color the diff
        if diff > 0:
            diff_str = f"{GREEN}{diff:10.6f}{RESET}"
        elif diff < 0:
            diff_str = f"{RED}{diff:10.6f}{RESET}"
        else:
            diff_str = f"{diff:10.6f}"

        line = (
            f"{name.ljust(name_width)}  "
            f"{total_small:12.6f}  "
            f"{total_large:12.6f}  "
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
         - diff_time_s = total_time_s_large - total_time_s_small
         - diff_occurrences = occurrences_large - occurrences_small
         - ratio_time_s = total_time_s_large / total_time_s_small (NaN if denominator=0)
    4. Returns a dictionary keyed by slice name with comparison metrics.

    Parameters
    ----------
    trace_files : list of str
        Exactly two Perfetto trace JSON file paths [small_trace, large_trace].
    parent_name : str
        The parent slice name whose children should be analyzed.

    Returns
    -------
    dict
        Dictionary keyed by slice name:
        {
          "slice_name": {
              "total_time_s_small": float,
              "total_time_s_large": float,
              "occurrences_small": int,
              "occurrences_large": int,
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
        "total_time_s_small": 0.123,
        "total_time_s_large": 0.250,
        "occurrences_small": 5,
        "occurrences_large": 8,
        "diff_time_s": 0.127,
        "diff_occurrences": 3,
        "ratio_time_s": 2.032
      },
      "bind_serial": {
        "total_time_s_small": 0.045,
        "total_time_s_large": 0.030,
        "occurrences_small": 2,
        "occurrences_large": 1,
        "diff_time_s": -0.015,
        "diff_occurrences": -1,
        "ratio_time_s": 0.667
      }
    }
    """
    assert len(trace_files) == 2

    # Compute breakdowns
    _df_small_linear, df_small = compute_breakdown(trace_files[0], parent_name)
    _df_large_linear, df_large = compute_breakdown(trace_files[1], parent_name)

    # Merge
    df_compare = pd.merge(
        df_small, df_large, on="name", how="outer", suffixes=("_small", "_large")
    ).fillna(0)

    # Compute differences
    df_compare["diff_time_s"] = (
        df_compare["total_time_s_large"] - df_compare["total_time_s_small"]
    )
    df_compare["diff_occurrences"] = (
        df_compare["occurrences_large"] - df_compare["occurrences_small"]
    )
    df_compare["ratio_time_s"] = np.where(
        df_compare["total_time_s_small"] == 0,
        np.nan,
        df_compare["total_time_s_large"] / df_compare["total_time_s_small"],
    )

    # Convert to dict: slice_name -> values
    comparison_dict = {
        row["name"]: {
            "total_time_s_small": row["total_time_s_small"],
            "total_time_s_large": row["total_time_s_large"],
            "occurrences_small": int(row["occurrences_small"]),
            "occurrences_large": int(row["occurrences_large"]),
            "diff_time_s": row["diff_time_s"],
            "diff_occurrences": int(row["diff_occurrences"]),
            "ratio_time_s": row["ratio_time_s"],
        }
        for _, row in df_compare.iterrows()
    }

    return comparison_dict
