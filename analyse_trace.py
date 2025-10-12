#!/usr/bin/env python3
"""
analyze_trace.py
Analyze a Perfetto trace JSON file and display the hierarchy of slices
with timing information and percentages.

Usage:
    python analyze_trace.py trace.json [-p "Root Slice Name"] [-a] [-f PATTERN] [--flat]

Options:
    -p, --parent        Root slice name to start from (default: auto-detect longest slice)
    -a, --aggregate     Aggregate repeated function calls and show counts
    -f, --filter        Filter slices by pattern (e.g., '*::bind', 'compute_*')
    --flat              Show flat list of matches instead of hierarchy (use with --filter)

Examples:
    # Show full hierarchy
    python analyze_trace.py trace.json
    
    # Show aggregated view with call counts
    python analyze_trace.py trace.json -a
    
    # Show only slices matching pattern in hierarchy
    python analyze_trace.py trace.json -f "*::bind"
    
    # Show flat list of all matching slices
    python analyze_trace.py trace.json -f "*::bind" --flat
    
    # Combine options
    python analyze_trace.py trace.json -p "Stage 3" -f "*compute*" -a
"""

import json
import argparse
import fnmatch
from typing import Dict, List, Optional, Tuple


class TraceSlice:
    """Represents a single trace slice with timing information."""
    
    def __init__(self, name: str, start_ts: float, end_ts: float, pid: int, tid: int):
        self.name = name
        self.start_ts = start_ts  # microseconds
        self.end_ts = end_ts      # microseconds
        self.duration = end_ts - start_ts
        self.pid = pid
        self.tid = tid
        self.children: List[TraceSlice] = []
        self.parent: Optional[TraceSlice] = None
    
    def add_child(self, child: 'TraceSlice'):
        """Add a child slice."""
        self.children.append(child)
        child.parent = self
    
    def contains(self, other: 'TraceSlice') -> bool:
        """Check if this slice contains another slice (by time range)."""
        return (self.start_ts <= other.start_ts and 
                self.end_ts >= other.end_ts and
                self.pid == other.pid and
                self.tid == other.tid)
    
    def duration_ms(self) -> float:
        """Get duration in milliseconds."""
        return self.duration / 1000.0
    
    def duration_sec(self) -> float:
        """Get duration in seconds."""
        return self.duration / 1_000_000.0


class AggregatedSlice:
    """Represents aggregated statistics for slices with the same name."""
    
    def __init__(self, name: str):
        self.name = name
        self.count = 0
        self.total_duration = 0.0
        self.children_by_name: Dict[str, 'AggregatedSlice'] = {}
    
    def add_slice(self, slice_obj: TraceSlice):
        """Add a slice to the aggregation."""
        self.count += 1
        self.total_duration += slice_obj.duration
        
        # Aggregate children
        for child in slice_obj.children:
            if child.name not in self.children_by_name:
                self.children_by_name[child.name] = AggregatedSlice(child.name)
            self.children_by_name[child.name].add_slice(child)
    
    def get_sorted_children(self) -> List['AggregatedSlice']:
        """Get children sorted by total duration (descending)."""
        return sorted(self.children_by_name.values(), 
                     key=lambda x: x.total_duration, reverse=True)


def parse_perfetto_json(filepath: str) -> List[TraceSlice]:
    """
    Parse a Perfetto JSON trace file and extract all slices.
    
    Returns a list of TraceSlice objects.
    """
    with open(filepath, 'r') as f:
        data = json.load(f)
    
    # Handle both formats: {"traceEvents": [...]} or [...]
    if isinstance(data, dict):
        trace_events = data.get('traceEvents', [])
    elif isinstance(data, list):
        trace_events = data
    else:
        trace_events = []
    
    # Dictionary to match Begin events with End events
    open_slices: Dict[Tuple[str, int, int], Tuple[float, dict]] = {}
    slices: List[TraceSlice] = []
    
    for event in trace_events:
        ph = event.get('ph')
        name = event.get('name', 'unknown')
        ts = event.get('ts', 0)
        pid = event.get('pid', 0)
        tid = event.get('tid', 0)
        
        # Handle duration events (ph='X')
        if ph == 'X':
            dur = event.get('dur', 0)
            slice_obj = TraceSlice(name, ts, ts + dur, pid, tid)
            slices.append(slice_obj)
        
        # Handle begin events (ph='B')
        elif ph == 'B':
            key = (name, pid, tid)
            open_slices[key] = (ts, event)
        
        # Handle end events (ph='E')
        elif ph == 'E':
            key = (name, pid, tid)
            if key in open_slices:
                start_ts, start_event = open_slices.pop(key)
                slice_obj = TraceSlice(name, start_ts, ts, pid, tid)
                slices.append(slice_obj)
    
    return slices


def build_hierarchy(slices: List[TraceSlice]) -> List[TraceSlice]:
    """
    Build a parent-child hierarchy from a flat list of slices.
    
    Returns a list of root slices (slices with no parents).
    """
    # Sort by start time, then by duration (longer first)
    slices_sorted = sorted(slices, key=lambda s: (s.start_ts, -(s.end_ts - s.start_ts)))
    
    # Build the tree
    roots = []
    
    for i, slice_obj in enumerate(slices_sorted):
        # Find the smallest containing parent
        parent_found = False
        for j in range(i - 1, -1, -1):
            potential_parent = slices_sorted[j]
            if potential_parent.contains(slice_obj):
                potential_parent.add_child(slice_obj)
                parent_found = True
                break
        
        if not parent_found:
            roots.append(slice_obj)
    
    return roots


def find_slice_by_name(roots: List[TraceSlice], name: str) -> Optional[TraceSlice]:
    """
    Find a slice by name in the hierarchy.
    """
    def search(slice_obj: TraceSlice) -> Optional[TraceSlice]:
        if slice_obj.name == name:
            return slice_obj
        for child in slice_obj.children:
            result = search(child)
            if result:
                return result
        return None
    
    for root in roots:
        result = search(root)
        if result:
            return result
    return None


def format_duration(duration_us: float) -> str:
    """
    Format duration in the most appropriate unit.
    
    Args:
        duration_us: Duration in microseconds
    
    Returns:
        Formatted string (e.g., "1.234s", "123.4ms", "12.3µs")
    """
    if duration_us >= 1_000_000:  # >= 1 second
        return f"{duration_us / 1_000_000:.3f}s"
    elif duration_us >= 1_000:  # >= 1 millisecond
        return f"{duration_us / 1_000:.3f}ms"
    else:  # microseconds
        return f"{duration_us:.1f}µs"


def print_hierarchy(slice_obj: TraceSlice, parent_duration: Optional[float] = None, 
                   prefix: str = "", is_last: bool = True):
    """
    Print the hierarchy tree with timing information.
    
    Args:
        slice_obj: The slice to print
        parent_duration: Duration of the parent (for percentage calculation)
        prefix: Prefix for tree formatting
        is_last: Whether this is the last child of its parent
    """
    # Calculate percentage relative to parent
    if parent_duration is None:
        parent_duration = slice_obj.duration
        percentage = 100.0
    else:
        percentage = (slice_obj.duration / parent_duration * 100.0) if parent_duration > 0 else 0.0
    
    # Format the duration
    duration_str = format_duration(slice_obj.duration)
    
    # Tree formatting
    connector = "└─ " if is_last else "├─ "
    print(f"{prefix}{connector}{slice_obj.name} ({duration_str}, {percentage:.1f}%)")
    
    # Prepare prefix for children
    if is_last:
        child_prefix = prefix + "   "
    else:
        child_prefix = prefix + "│  "
    
    # Print children
    for i, child in enumerate(slice_obj.children):
        is_last_child = (i == len(slice_obj.children) - 1)
        print_hierarchy(child, slice_obj.duration, child_prefix, is_last_child)


def print_aggregated_hierarchy(agg_slice: AggregatedSlice, parent_duration: Optional[float] = None,
                               prefix: str = "", is_last: bool = True):
    """
    Print the aggregated hierarchy tree with call counts and total timing.
    
    Args:
        agg_slice: The aggregated slice to print
        parent_duration: Duration of the parent (for percentage calculation)
        prefix: Prefix for tree formatting
        is_last: Whether this is the last child of its parent
    """
    # Calculate percentage relative to parent
    if parent_duration is None:
        parent_duration = agg_slice.total_duration
        percentage = 100.0
    else:
        percentage = (agg_slice.total_duration / parent_duration * 100.0) if parent_duration > 0 else 0.0
    
    # Format the duration
    duration_str = format_duration(agg_slice.total_duration)
    
    # Add call count if > 1
    count_str = f" [×{agg_slice.count}]" if agg_slice.count > 1 else ""
    
    # Tree formatting
    connector = "└─ " if is_last else "├─ "
    print(f"{prefix}{connector}{agg_slice.name}{count_str} ({duration_str}, {percentage:.1f}%)")
    
    # Prepare prefix for children
    if is_last:
        child_prefix = prefix + "   "
    else:
        child_prefix = prefix + "│  "
    
    # Print children
    children = agg_slice.get_sorted_children()
    for i, child in enumerate(children):
        is_last_child = (i == len(children) - 1)
        print_aggregated_hierarchy(child, agg_slice.total_duration, child_prefix, is_last_child)


def matches_pattern(name: str, pattern: str) -> bool:
    """Check if a name matches a glob pattern (e.g., '*::bind')."""
    return fnmatch.fnmatch(name, pattern)


def filter_slice_hierarchy(slice_obj: TraceSlice, pattern: str) -> Optional[TraceSlice]:
    """
    Filter a slice hierarchy to only include slices matching the pattern.
    Returns a new slice tree with only matching slices and their children.
    Returns None if this slice and none of its descendants match.
    """
    # Check if this slice matches
    this_matches = matches_pattern(slice_obj.name, pattern)
    
    # Recursively filter children
    filtered_children = []
    for child in slice_obj.children:
        filtered_child = filter_slice_hierarchy(child, pattern)
        if filtered_child:
            filtered_children.append(filtered_child)
    
    # Include this slice if it matches OR if any children match
    if this_matches or filtered_children:
        # Create a copy of this slice
        filtered_slice = TraceSlice(
            slice_obj.name,
            slice_obj.start_ts,
            slice_obj.end_ts,
            slice_obj.pid,
            slice_obj.tid
        )
        filtered_slice.children = filtered_children
        for child in filtered_children:
            child.parent = filtered_slice
        return filtered_slice
    
    return None


def collect_matching_slices(slice_obj: TraceSlice, pattern: str, matches: List[TraceSlice]):
    """
    Collect all slices matching the pattern into a flat list.
    """
    if matches_pattern(slice_obj.name, pattern):
        matches.append(slice_obj)
    
    for child in slice_obj.children:
        collect_matching_slices(child, pattern, matches)


def print_flat_matches(slices: List[TraceSlice], pattern: str, root_duration: float, aggregate: bool = False):
    """
    Print a flat list of matching slices sorted by duration.
    
    Args:
        slices: List of matching slices
        pattern: The pattern that was used to filter
        root_duration: Total duration of the root slice for percentage calculation
        aggregate: If True, group by name and show aggregated statistics
    """
    if not slices:
        print(f"No slices matching pattern '{pattern}' found.")
        return
    
    if aggregate:
        # Aggregate by name
        aggregated: Dict[str, Tuple[int, float]] = {}  # name -> (count, total_duration)
        for slice_obj in slices:
            if slice_obj.name not in aggregated:
                aggregated[slice_obj.name] = (0, 0.0)
            count, duration = aggregated[slice_obj.name]
            aggregated[slice_obj.name] = (count + 1, duration + slice_obj.duration)
        
        # Sort by total duration descending
        sorted_items = sorted(aggregated.items(), key=lambda x: x[1][1], reverse=True)
        
        total_count = len(slices)
        total_duration = sum(s.duration for s in slices)
        
        print(f"Found {len(sorted_items)} unique slices matching '{pattern}' ({total_count} total calls):")
        print("=" * 110)
        print(f"{'Name':<45} {'Count':>8} {'Duration':>15} {'% of Matches':>12} {'% of Total':>12}")
        print("-" * 110)
        
        for name, (count, duration) in sorted_items:
            duration_str = format_duration(duration)
            count_str = f"×{count}"
            pct_of_matches = (duration / total_duration * 100.0) if total_duration > 0 else 0.0
            pct_of_total = (duration / root_duration * 100.0) if root_duration > 0 else 0.0
            print(f"{name:<45} {count_str:>8} {duration_str:>15} {pct_of_matches:>11.1f}% {pct_of_total:>11.1f}%")
        
        print("-" * 110)
        total_pct_of_root = (total_duration / root_duration * 100.0) if root_duration > 0 else 0.0
        print(f"{'Total':>45} {'×' + str(total_count):>8} {format_duration(total_duration):>15} {'100.0%':>12} {total_pct_of_root:>11.1f}%")
    else:
        # Non-aggregated: show each slice individually
        sorted_slices = sorted(slices, key=lambda s: s.duration, reverse=True)
        
        print(f"Found {len(sorted_slices)} slices matching '{pattern}':")
        print("=" * 100)
        
        total_duration = sum(s.duration for s in sorted_slices)
        print(f"{'Name':<45} {'Duration':>15} {'% of Matches':>12} {'% of Total':>12}")
        print("-" * 100)
        
        for slice_obj in sorted_slices:
            duration_str = format_duration(slice_obj.duration)
            pct_of_matches = (slice_obj.duration / total_duration * 100.0) if total_duration > 0 else 0.0
            pct_of_total = (slice_obj.duration / root_duration * 100.0) if root_duration > 0 else 0.0
            print(f"{slice_obj.name:<45} {duration_str:>15} {pct_of_matches:>11.1f}% {pct_of_total:>11.1f}%")
        
        print("-" * 100)
        total_pct_of_root = (total_duration / root_duration * 100.0) if root_duration > 0 else 0.0
        print(f"{'Total':>45} {format_duration(total_duration):>15} {'100.0%':>12} {total_pct_of_root:>11.1f}%")




def aggregate_slice(slice_obj: TraceSlice) -> AggregatedSlice:
    """
    Create an aggregated view of a slice hierarchy.
    
    Args:
        slice_obj: The root slice to aggregate
    
    Returns:
        An AggregatedSlice with children grouped by name
    """
    agg = AggregatedSlice(slice_obj.name)
    agg.add_slice(slice_obj)
    return agg


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Analyze a Perfetto trace file and display the hierarchy."
    )
    parser.add_argument(
        "trace_file",
        help="Path to the Perfetto JSON trace file."
    )
    parser.add_argument(
        "--parent", "-p",
        help="Root slice name to start from (default: auto-detect)",
        default=None
    )
    parser.add_argument(
        "--aggregate", "-a",
        action="store_true",
        help="Aggregate repeated function calls and show counts"
    )
    parser.add_argument(
        "--filter", "-f",
        help="Filter slices by pattern (e.g., '*::bind', 'compute_*')",
        default=None
    )
    parser.add_argument(
        "--flat",
        action="store_true",
        help="Show flat list of matches instead of hierarchy (use with --filter)"
    )
    
    args = parser.parse_args()
    
    # Parse the trace file
    print(f"Parsing {args.trace_file}...")
    slices = parse_perfetto_json(args.trace_file)
    print(f"Found {len(slices)} slices.")
    
    # Build hierarchy
    print("Building hierarchy...")
    roots = build_hierarchy(slices)
    
    # Find the root to display
    if args.parent:
        root = find_slice_by_name(roots, args.parent)
        if not root:
            print(f"Error: Could not find slice named '{args.parent}'")
            return
        roots_to_display = [root]
    else:
        # Auto-detect: use the longest root slice
        if roots:
            roots_to_display = sorted(roots, key=lambda s: s.duration, reverse=True)[:1]
        else:
            print("Error: No root slices found in trace.")
            return
    
    # Apply filtering if requested
    if args.filter:
        if args.flat:
            # Flat view: collect all matching slices
            all_matches = []
            for root in roots_to_display:
                collect_matching_slices(root, args.filter, all_matches)
            
            # Calculate total root duration for percentage calculation
            root_duration = sum(root.duration for root in roots_to_display)
            
            print()
            print_flat_matches(all_matches, args.filter, root_duration, aggregate=args.aggregate)
            return
        else:
            # Hierarchical view: filter the tree
            filtered_roots = []
            for root in roots_to_display:
                filtered = filter_slice_hierarchy(root, args.filter)
                if filtered:
                    filtered_roots.append(filtered)
            
            if not filtered_roots:
                print(f"\nNo slices matching pattern '{args.filter}' found.")
                return
            
            roots_to_display = filtered_roots
    
    # Display the hierarchy
    mode_parts = []
    if args.aggregate:
        mode_parts.append("Aggregated")
    else:
        mode_parts.append("Detailed")
    
    if args.filter:
        mode_parts.append(f"Filtered: '{args.filter}'")
    
    mode = " - ".join(mode_parts)
    print(f"\nTrace Hierarchy ({mode}):")
    print("=" * 80)
    
    for root in roots_to_display:
        if args.aggregate:
            agg_root = aggregate_slice(root)
            print_aggregated_hierarchy(agg_root)
        else:
            print_hierarchy(root)
        print()


if __name__ == "__main__":
    main()
