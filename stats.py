def print_with_stats(
    comparison_dict, trace_files, sort_option="linear", max_name_width=40
):
    """
    Display comparison data as a pandas DataFrame.

    - If ≤ 7 traces: shows slice name, total_time_s for each trace, plus Max, Min, Median, Mean, Range, Ratio.
    - If > 7 traces: shows only slice name and stats columns.

    Stats columns: Max, Min, Median, Mean, Range, Ratio.
    """

    from pathlib import Path

    import numpy as np
    import pandas as pd

    if not comparison_dict:
        print("No slices to display.")
        return

    n_traces_total = len(trace_files)
    show_all_columns = n_traces_total <= 7
    n_traces = min(n_traces_total, 7)
    trace_files = trace_files[:n_traces]

    # Shorten trace names for display
    display_names = [f"{Path(f).stem[:5]}{i+1}" for i, f in enumerate(trace_files)]
    total_keys = [f"total_time_s_{Path(f).stem}" for f in trace_files]

    # Prepare the DataFrame
    rows = []
    index = []

    for name, stats in comparison_dict.items():
        values = [stats.get(k, 0.0) for k in total_keys]
        max_val = max(values)
        min_val = min(values)
        median_val = np.median(values)
        mean_val = np.mean(values)
        rng = max_val - min_val
        ratio = float("nan") if min_val == 0 else max_val / min_val

        row = dict(zip(display_names, values)) if show_all_columns else {}
        row.update(
            {
                "Max": max_val,
                "Min": min_val,
                "Median": median_val,
                "Mean": mean_val,
                "Range": rng,
                "Ratio": ratio,
            }
        )

        rows.append(row)
        index.append(
            name if len(name) <= max_name_width else name[: max_name_width - 3] + "..."
        )

    df = pd.DataFrame(rows, index=index)

    # Sorting if required
    if sort_option.startswith("time_") and show_all_columns:
        trace_idx = int(sort_option.split("_")[1]) - 1
        if 0 <= trace_idx < n_traces:
            col_to_sort = display_names[trace_idx]
            df = df.sort_values(by=col_to_sort, ascending=False)

    # Final display
    if show_all_columns:
        pd.set_option("display.width", None)
        pd.set_option("display.max_columns", None)
        print(df.round(6))
    else:
        print(df[["Max", "Min", "Median", "Mean", "Range", "Ratio"]].round(6))

    print()
