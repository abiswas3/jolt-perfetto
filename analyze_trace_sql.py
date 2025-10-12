#!/usr/bin/env python3
"""
analyze_trace_sql.py
Analyze a Perfetto trace file using the trace processor SQL API.
Provides accurate hierarchy with the same interface as analyze_trace.py.

Usage:
    python analyze_trace_sql.py trace.json [-p "Root Slice Name"] [-a] [-f PATTERN] [--flat]

Requires:
    pip install perfetto --break-system-packages
"""

import argparse
import fnmatch
from typing import Dict, List, Optional, Tuple
from perfetto.trace_processor import TraceProcessor


class SliceNode:
    """Represents a slice in the hierarchy."""
    
    def __init__(self, id: int, name: str, ts: int, dur: int, parent_id: Optional[int] = None):
        self.id = id
        self.name = name
        self.ts = ts  # nanoseconds
        self.dur = dur  # nanoseconds
        self.parent_id = parent_id
        self.children: List['SliceNode'] = []
    
    def duration_us(self) -> float:
        """Get duration in microseconds."""
        return self.dur / 1000.0
    
    def add_child(self, child: 'SliceNode'):
        """Add a child slice."""
        self.children.append(child)


class AggregatedSlice:
    """Aggregated statistics for slices with the same name."""
    
    def __init__(self, name: str):
        self.name = name
        self.count = 0
        self.total_duration = 0.0
        self.children_by_name: Dict[str, 'AggregatedSlice'] = {}
    
    def add_slice(self, slice_node: SliceNode):
        """Add a slice to the aggregation."""
        self.count += 1
        self.total_duration += slice_node.duration_us()
        
        for child in slice_node.children:
            if child.name not in self.children_by_name:
                self.children_by_name[child.name] = AggregatedSlice(child.name)
            self.children_by_name[child.name].add_slice(child)
    
    def get_sorted_children(self) -> List['AggregatedSlice']:
        """Get children sorted by total duration (descending)."""
        return sorted(self.children_by_name.values(), 
                     key=lambda x: x.total_duration, reverse=True)


def load_trace_slices(trace_file: str) -> Tuple[TraceProcessor, List[SliceNode], Dict[int, SliceNode]]:
    """
    Load trace and build slice hierarchy using trace processor.
    
    Returns:
        (trace_processor, root_slices, all_slices_by_id)
    """
    tp = TraceProcessor(trace=trace_file)
    
    # Query all slices
    query_result = tp.query("""
        SELECT 
            id,
            name,
            ts,
            dur,
            parent_id,
            depth
        FROM slice
        ORDER BY depth, ts
    """)
    
    all_slices = {}
    root_slices = []
    
    # Build slice nodes
    for row in query_result:
        slice_id = row.id
        name = row.name
        ts = row.ts
        dur = row.dur
        parent_id = row.parent_id if row.parent_id else None
        
        slice_node = SliceNode(slice_id, name, ts, dur, parent_id)
        all_slices[slice_id] = slice_node
        
        if parent_id is None:
            root_slices.append(slice_node)
    
    # Build parent-child relationships
    for slice_node in all_slices.values():
        if slice_node.parent_id is not None and slice_node.parent_id in all_slices:
            parent = all_slices[slice_node.parent_id]
            parent.add_child(slice_node)
    
    return tp, root_slices, all_slices


def find_slice_by_name(slices: List[SliceNode], name: str) -> Optional[SliceNode]:
    """Find a slice by name in the hierarchy."""
    def search(slice_node: SliceNode) -> Optional[SliceNode]:
        if slice_node.name == name:
            return slice_node
        for child in slice_node.children:
            result = search(child)
            if result:
                return result
        return None
    
    for root in slices:
        result = search(root)
        if result:
            return result
    return None


def format_duration(duration_us: float) -> str:
    """Format duration in the most appropriate unit."""
    if duration_us >= 1_000_000:  # >= 1 second
        return f"{duration_us / 1_000_000:.3f}s"
    elif duration_us >= 1_000:  # >= 1 millisecond
        return f"{duration_us / 1_000:.3f}ms"
    else:  # microseconds
        return f"{duration_us:.1f}µs"


def matches_pattern(name: str, pattern: str) -> bool:
    """Check if a name matches a glob pattern."""
    return fnmatch.fnmatch(name, pattern)


def filter_slice_hierarchy(slice_node: SliceNode, pattern: str) -> Optional[SliceNode]:
    """Filter a slice hierarchy to only include slices matching the pattern."""
    this_matches = matches_pattern(slice_node.name, pattern)
    
    filtered_children = []
    for child in slice_node.children:
        filtered_child = filter_slice_hierarchy(child, pattern)
        if filtered_child:
            filtered_children.append(filtered_child)
    
    if this_matches or filtered_children:
        filtered_slice = SliceNode(
            slice_node.id,
            slice_node.name,
            slice_node.ts,
            slice_node.dur,
            slice_node.parent_id
        )
        filtered_slice.children = filtered_children
        return filtered_slice
    
    return None


def collect_matching_slices(slice_node: SliceNode, pattern: str, matches: List[SliceNode]):
    """Collect all slices matching the pattern into a flat list."""
    if matches_pattern(slice_node.name, pattern):
        matches.append(slice_node)
    
    for child in slice_node.children:
        collect_matching_slices(child, pattern, matches)


def aggregate_slice(slice_node: SliceNode) -> AggregatedSlice:
    """Create an aggregated view of a slice hierarchy."""
    agg = AggregatedSlice(slice_node.name)
    agg.add_slice(slice_node)
    return agg


def print_hierarchy(slice_node: SliceNode, parent_duration: Optional[float] = None,
                   prefix: str = "", is_last: bool = True):
    """Print the hierarchy tree with timing information."""
    if parent_duration is None:
        parent_duration = slice_node.duration_us()
        percentage = 100.0
    else:
        percentage = (slice_node.duration_us() / parent_duration * 100.0) if parent_duration > 0 else 0.0
    
    duration_str = format_duration(slice_node.duration_us())
    
    connector = "└─ " if is_last else "├─ "
    print(f"{prefix}{connector}{slice_node.name} ({duration_str}, {percentage:.1f}%)")
    
    if is_last:
        child_prefix = prefix + "   "
    else:
        child_prefix = prefix + "│  "
    
    for i, child in enumerate(slice_node.children):
        is_last_child = (i == len(slice_node.children) - 1)
        print_hierarchy(child, slice_node.duration_us(), child_prefix, is_last_child)


def print_aggregated_hierarchy(agg_slice: AggregatedSlice, parent_duration: Optional[float] = None,
                               prefix: str = "", is_last: bool = True):
    """Print the aggregated hierarchy tree with call counts and total timing."""
    if parent_duration is None:
        parent_duration = agg_slice.total_duration
        percentage = 100.0
    else:
        percentage = (agg_slice.total_duration / parent_duration * 100.0) if parent_duration > 0 else 0.0
    
    duration_str = format_duration(agg_slice.total_duration)
    count_str = f" [×{agg_slice.count}]" if agg_slice.count > 1 else ""
    
    connector = "└─ " if is_last else "├─ "
    print(f"{prefix}{connector}{agg_slice.name}{count_str} ({duration_str}, {percentage:.1f}%)")
    
    if is_last:
        child_prefix = prefix + "   "
    else:
        child_prefix = prefix + "│  "
    
    children = agg_slice.get_sorted_children()
    for i, child in enumerate(children):
        is_last_child = (i == len(children) - 1)
        print_aggregated_hierarchy(child, agg_slice.total_duration, child_prefix, is_last_child)


def print_flat_matches(slices: List[SliceNode], pattern: str, root_duration: float, aggregate: bool = False):
    """Print a flat list of matching slices sorted by duration."""
    if not slices:
        print(f"No slices matching pattern '{pattern}' found.")
        return
    
    if aggregate:
        # Aggregate by name
        aggregated: Dict[str, Tuple[int, float]] = {}
        for slice_node in slices:
            if slice_node.name not in aggregated:
                aggregated[slice_node.name] = (0, 0.0)
            count, duration = aggregated[slice_node.name]
            aggregated[slice_node.name] = (count + 1, duration + slice_node.duration_us())
        
        sorted_items = sorted(aggregated.items(), key=lambda x: x[1][1], reverse=True)
        
        total_count = len(slices)
        total_duration = sum(s.duration_us() for s in slices)
        
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
        sorted_slices = sorted(slices, key=lambda s: s.duration_us(), reverse=True)
        
        print(f"Found {len(sorted_slices)} slices matching '{pattern}':")
        print("=" * 100)
        
        total_duration = sum(s.duration_us() for s in sorted_slices)
        print(f"{'Name':<45} {'Duration':>15} {'% of Matches':>12} {'% of Total':>12}")
        print("-" * 100)
        
        for slice_node in sorted_slices:
            duration_str = format_duration(slice_node.duration_us())
            pct_of_matches = (slice_node.duration_us() / total_duration * 100.0) if total_duration > 0 else 0.0
            pct_of_total = (slice_node.duration_us() / root_duration * 100.0) if root_duration > 0 else 0.0
            print(f"{slice_node.name:<45} {duration_str:>15} {pct_of_matches:>11.1f}% {pct_of_total:>11.1f}%")
        
        print("-" * 100)
        total_pct_of_root = (total_duration / root_duration * 100.0) if root_duration > 0 else 0.0
        print(f"{'Total':>45} {format_duration(total_duration):>15} {'100.0%':>12} {total_pct_of_root:>11.1f}%")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Analyze a Perfetto trace file using SQL trace processor."
    )
    parser.add_argument(
        "trace_file",
        help="Path to the Perfetto trace file."
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
    
    # Load trace
    print(f"Loading trace from {args.trace_file}...")
    tp, roots, all_slices = load_trace_slices(args.trace_file)
    print(f"Found {len(all_slices)} slices total, {len(roots)} root slices.")
    
    # Find the root to display
    if args.parent:
        root = find_slice_by_name(roots, args.parent)
        if not root:
            print(f"Error: Could not find slice named '{args.parent}'")
            tp.close()
            return
        roots_to_display = [root]
    else:
        # Auto-detect: use the longest root slice
        if roots:
            roots_to_display = sorted(roots, key=lambda s: s.dur, reverse=True)[:1]
        else:
            print("Error: No root slices found in trace.")
            tp.close()
            return
    
    # Apply filtering if requested
    if args.filter:
        if args.flat:
            # Flat view: collect all matching slices
            all_matches = []
            for root in roots_to_display:
                collect_matching_slices(root, args.filter, all_matches)
            
            root_duration = sum(r.duration_us() for r in roots_to_display)
            
            print()
            print_flat_matches(all_matches, args.filter, root_duration, aggregate=args.aggregate)
            tp.close()
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
                tp.close()
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
    
    tp.close()


if __name__ == "__main__":
    main()
