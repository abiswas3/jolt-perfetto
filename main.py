from helpers import compare_two, compute_breakdown, print_nice

trace_files = ["trace-small_b.json", "trace-large.json"]
p_name = "Stage 3 sumchecks"

# Display nicely in notebook
comparison_dict = compare_two(trace_files, p_name)
# display(JSON(comparison_dict, expanded=True))
print_nice(comparison_dict)
