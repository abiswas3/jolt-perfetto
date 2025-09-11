def print_with_stats(
    comparison_dict, trace_files, sort_option="linear", max_name_width=40
):
    """
    Pretty-print a comparison dictionary with table-like formatting for multiple traces.

    Shows slice name, total_time_s for each trace, plus Range and Variance columns.

    If more than 7 traces, only the first 7 are shown. Trace names shortened to first 5 chars + index.
    """
    from pathlib import Path

    import numpy as np

    if not comparison_dict:
        print("No slices to display.")
        return

    # Limit number of traces to display
    n_traces = min(len(trace_files), 7)
    trace_files = trace_files[:n_traces]

    # Shorten trace names for display
    display_names = [f"{Path(f).stem[:5]}{i+1}" for i, f in enumerate(trace_files)]

    # Gather total_time keys for the traces
    total_keys = [f"total_time_s_{Path(f).stem}" for f in trace_files]

    # Compute column widths
    name_width = min(max(len(name) for name in comparison_dict.keys()), max_name_width)
    col_widths = []
    for key in total_keys:
        col_width = (
            max(
                len(display_names[total_keys.index(key)]),
                *(len(f"{v[key]:.6f}") for v in comparison_dict.values()),
            )
            + 2
        )
        col_widths.append(col_width)

    # Widths for the new columns
    range_width = max(5, len("Range")) + 2
    var_width = max(8, len("Variance")) + 2

    # Header
    header = "Name".ljust(name_width)
    for dn, w in zip(display_names, col_widths):
        header += f"  {dn.rjust(w)}"
    header += f"  {'Range'.rjust(range_width)}  {'Ratio'.rjust(var_width)}"
    print(header)
    print("-" * (len(header) + 2))

    # Decide sorting
    items = comparison_dict.items()
    if sort_option.startswith("time_"):
        trace_idx = int(sort_option.split("_")[1]) - 1
        if 0 <= trace_idx < n_traces:
            items = sorted(
                items, key=lambda x: x[1][total_keys[trace_idx]], reverse=True
            )

    # Print rows
    for name, stats in items:
        display_name = (
            name if len(name) <= max_name_width else name[: max_name_width - 3] + "..."
        )
        line = display_name.ljust(name_width)

        values = [stats[k] for k in total_keys]

        for k, w in zip(total_keys, col_widths):
            line += f"  {stats[k]:>{w}.6f}"

        # Compute max - min and variance
        rng = max(values) - min(values)
        # Compute max/min ratio safely
        min_val = min(values)
        if min_val == 0:
            ratio = float("nan")
        else:
            ratio = max(values) / min_val
        line += f"  {rng:>{range_width}.6f}  {ratio:>{var_width}.6f}"
        print(line)
    print()
