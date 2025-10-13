#!/usr/bin/env python3
"""
compare_trace_hierarchy_sql.py
Compare two Perfetto trace files using the trace processor SQL API.
Provides accurate hierarchy comparison with the same interface as compare_trace_hierarchy.py.

Usage:
    python compare_trace_hierarchy_sql.py trace1.json trace2.json [-p "Root"] [-a] [-f PATTERN] [--flat]

Requires:
    pip install perfetto --break-system-packages
"""

import argparse
import fnmatch
import re
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
    """Load trace and build slice hierarchy using trace processor."""
    tp = TraceProcessor(trace=trace_file)
    
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
    if duration_us >= 1_000_000:
        return f"{duration_us / 1_000_000:.3f}s"
    elif duration_us >= 1_000:
        return f"{duration_us / 1_000:.3f}ms"
    else:
        return f"{duration_us:.1f}µs"


def format_diff(diff_us: float) -> str:
    """Format duration difference with +/- sign."""
    if diff_us >= 0:
        return "+" + format_duration(diff_us)
    else:
        return "-" + format_duration(abs(diff_us))


def visible_length(s: str) -> int:
    """Calculate visible length of string, excluding ANSI color codes."""
    ansi_escape = re.compile(r'\033\[[0-9;]*m')
    return len(ansi_escape.sub('', s))


def pad_with_color(s: str, width: int, align: str = '>') -> str:
    """Pad a string that may contain ANSI color codes."""
    visible_len = visible_length(s)
    padding_needed = max(0, width - visible_len)
    
    if align == '>':
        return ' ' * padding_needed + s
    elif align == '<':
        return s + ' ' * padding_needed
    elif align == '^':
        left_pad = padding_needed // 2
        right_pad = padding_needed - left_pad
        return ' ' * left_pad + s + ' ' * right_pad
    return s


def colorize_diff(diff_str: str, rel_change_str: str) -> tuple:
    """Add color coding to difference strings."""
    RED = '\033[91m'
    GREEN = '\033[92m'
    RESET = '\033[0m'
    
    if diff_str.startswith('+') and diff_str not in ["NEW", "REMOVED"]:
        color = RED
    elif diff_str.startswith('-'):
        color = GREEN
    else:
        color = ''
    
    if color:
        colored_diff = f"{color}{diff_str}{RESET}"
        colored_rel = f"{color}{rel_change_str}{RESET}"
    else:
        colored_diff = diff_str
        colored_rel = rel_change_str
    
    return colored_diff, colored_rel


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


def print_hierarchy_comparison(slice1: Optional[SliceNode], slice2: Optional[SliceNode],
                               parent_duration1: Optional[float] = None,
                               parent_duration2: Optional[float] = None,
                               prefix: str = "", is_last: bool = True):
    """Print side-by-side comparison of two hierarchies."""
    if slice1 is None and slice2 is None:
        return
    
    name = slice1.name if slice1 else slice2.name
    
    # Calculate percentages
    if slice1:
        if parent_duration1 is None:
            parent_duration1 = slice1.duration_us()
            pct1 = 100.0
        else:
            pct1 = (slice1.duration_us() / parent_duration1 * 100.0) if parent_duration1 > 0 else 0.0
        dur1_str = format_duration(slice1.duration_us())
    else:
        pct1 = 0.0
        dur1_str = "---"
    
    if slice2:
        if parent_duration2 is None:
            parent_duration2 = slice2.duration_us()
            pct2 = 100.0
        else:
            pct2 = (slice2.duration_us() / parent_duration2 * 100.0) if parent_duration2 > 0 else 0.0
        dur2_str = format_duration(slice2.duration_us())
    else:
        pct2 = 0.0
        dur2_str = "---"
    
    # Calculate difference
    if slice1 and slice2:
        diff = slice2.duration_us() - slice1.duration_us()
        diff_str = format_diff(diff)
        rel_change_pct = (diff / slice1.duration_us() * 100.0) if slice1.duration_us() > 0 else 0.0
        rel_change_str = f"{rel_change_pct:+.1f}%"
        diff_str, rel_change_str = colorize_diff(diff_str, rel_change_str)
        diff_str = pad_with_color(diff_str, 12, '>')
        rel_change_str = pad_with_color(rel_change_str, 8, '>')
    else:
        diff_str = "NEW" if slice2 and not slice1 else "REMOVED"
        rel_change_str = ""
        diff_str = f"{diff_str:>12}"
        rel_change_str = f"{rel_change_str:>8}"
    
    # Tree formatting
    connector = "└─ " if is_last else "├─ "
    name_col_width = 60
    current_length = len(prefix) + len(connector) + len(name)
    padding = max(1, name_col_width - current_length)
    
    print(f"{prefix}{connector}{name}{' ' * padding}{dur1_str:>12} ({pct1:>5.1f}%)  {dur2_str:>12} ({pct2:>5.1f}%)  {diff_str} {rel_change_str}")
    
    if is_last:
        child_prefix = prefix + "   "
    else:
        child_prefix = prefix + "│  "
    
    # Match children by name
    children1 = {c.name: c for c in (slice1.children if slice1 else [])}
    children2 = {c.name: c for c in (slice2.children if slice2 else [])}
    all_child_names = sorted(set(children1.keys()) | set(children2.keys()))
    
    for i, child_name in enumerate(all_child_names):
        is_last_child = (i == len(all_child_names) - 1)
        child1 = children1.get(child_name)
        child2 = children2.get(child_name)
        print_hierarchy_comparison(
            child1, child2,
            slice1.duration_us() if slice1 else None,
            slice2.duration_us() if slice2 else None,
            child_prefix, is_last_child
        )


def print_aggregated_comparison(agg1: Optional[AggregatedSlice], agg2: Optional[AggregatedSlice],
                                parent_duration1: Optional[float] = None,
                                parent_duration2: Optional[float] = None,
                                prefix: str = "", is_last: bool = True):
    """Print side-by-side comparison of aggregated hierarchies."""
    if agg1 is None and agg2 is None:
        return
    
    name = agg1.name if agg1 else agg2.name
    
    # Calculate percentages
    if agg1:
        if parent_duration1 is None:
            parent_duration1 = agg1.total_duration
            pct1 = 100.0
        else:
            pct1 = (agg1.total_duration / parent_duration1 * 100.0) if parent_duration1 > 0 else 0.0
        dur1_str = format_duration(agg1.total_duration)
        count1_str = f"[×{agg1.count}]" if agg1.count > 1 else ""
    else:
        pct1 = 0.0
        dur1_str = "---"
        count1_str = ""
    
    if agg2:
        if parent_duration2 is None:
            parent_duration2 = agg2.total_duration
            pct2 = 100.0
        else:
            pct2 = (agg2.total_duration / parent_duration2 * 100.0) if parent_duration2 > 0 else 0.0
        dur2_str = format_duration(agg2.total_duration)
        count2_str = f"[×{agg2.count}]" if agg2.count > 1 else ""
    else:
        pct2 = 0.0
        dur2_str = "---"
        count2_str = ""
    
    # Calculate difference
    if agg1 and agg2:
        diff = agg2.total_duration - agg1.total_duration
        diff_str = format_diff(diff)
        rel_change_pct = (diff / agg1.total_duration * 100.0) if agg1.total_duration > 0 else 0.0
        rel_change_str = f"{rel_change_pct:+.1f}%"
        diff_str, rel_change_str = colorize_diff(diff_str, rel_change_str)
        diff_str = pad_with_color(diff_str, 12, '>')
        rel_change_str = pad_with_color(rel_change_str, 8, '>')
        count_diff = agg2.count - agg1.count
        count_diff_str = f"({count_diff:+d})" if count_diff != 0 else ""
    else:
        diff_str = "NEW" if agg2 and not agg1 else "REMOVED"
        rel_change_str = ""
        diff_str = f"{diff_str:>12}"
        rel_change_str = f"{rel_change_str:>8}"
        count_diff_str = ""
    
    # Tree formatting
    connector = "└─ " if is_last else "├─ "
    name_with_count = f"{name} {count1_str:>6} {count2_str:>6} {count_diff_str}"
    
    name_col_width = 70
    current_length = len(prefix) + len(connector) + len(name_with_count)
    padding = max(1, name_col_width - current_length)
    
    print(f"{prefix}{connector}{name_with_count}{' ' * padding}{dur1_str:>12} ({pct1:>5.1f}%)  {dur2_str:>12} ({pct2:>5.1f}%)  {diff_str} {rel_change_str}")
    
    if is_last:
        child_prefix = prefix + "   "
    else:
        child_prefix = prefix + "│  "
    
    # Match children by name
    children1_dict = {c.name: c for c in (agg1.get_sorted_children() if agg1 else [])}
    children2_dict = {c.name: c for c in (agg2.get_sorted_children() if agg2 else [])}
    all_child_names = sorted(set(children1_dict.keys()) | set(children2_dict.keys()),
                            key=lambda n: max(
                                children1_dict.get(n, AggregatedSlice(n)).total_duration,
                                children2_dict.get(n, AggregatedSlice(n)).total_duration
                            ), reverse=True)
    
    for i, child_name in enumerate(all_child_names):
        is_last_child = (i == len(all_child_names) - 1)
        child1 = children1_dict.get(child_name)
        child2 = children2_dict.get(child_name)
        print_aggregated_comparison(
            child1, child2,
            agg1.total_duration if agg1 else None,
            agg2.total_duration if agg2 else None,
            child_prefix, is_last_child
        )


def print_flat_comparison(slices1: List[SliceNode], slices2: List[SliceNode],
                         pattern: str, root_duration1: float, root_duration2: float,
                         aggregate: bool = False):
    """Print flat comparison of matching slices from two traces."""
    if aggregate:
        # Aggregate by name
        agg1: Dict[str, Tuple[int, float]] = {}
        for s in slices1:
            if s.name not in agg1:
                agg1[s.name] = (0, 0.0)
            count, dur = agg1[s.name]
            agg1[s.name] = (count + 1, dur + s.duration_us())
        
        agg2: Dict[str, Tuple[int, float]] = {}
        for s in slices2:
            if s.name not in agg2:
                agg2[s.name] = (0, 0.0)
            count, dur = agg2[s.name]
            agg2[s.name] = (count + 1, dur + s.duration_us())
        
        all_names = sorted(set(agg1.keys()) | set(agg2.keys()))
        
        total_dur1 = sum(s.duration_us() for s in slices1)
        total_dur2 = sum(s.duration_us() for s in slices2)
        total_count1 = len(slices1)
        total_count2 = len(slices2)
        
        print(f"Comparing slices matching '{pattern}':")
        print(f"Trace 1: {len(agg1)} unique ({total_count1} total calls)")
        print(f"Trace 2: {len(agg2)} unique ({total_count2} total calls)")
        print("=" * 130)
        print(f"{'Name':<40} {'Count':>8} {'Trace 1':>15} {'% Total':>8}  {'Count':>8} {'Trace 2':>15} {'% Total':>8}  {'Diff':>12}")
        print("-" * 130)
        
        for name in all_names:
            count1, dur1 = agg1.get(name, (0, 0.0))
            count2, dur2 = agg2.get(name, (0, 0.0))
            
            dur1_str = format_duration(dur1) if count1 > 0 else "---"
            dur2_str = format_duration(dur2) if count2 > 0 else "---"
            pct1 = (dur1 / root_duration1 * 100.0) if root_duration1 > 0 and count1 > 0 else 0.0
            pct2 = (dur2 / root_duration2 * 100.0) if root_duration2 > 0 and count2 > 0 else 0.0
            
            if count1 > 0 and count2 > 0:
                diff = dur2 - dur1
                diff_str = format_diff(diff)
                rel_change_pct = (diff / dur1 * 100.0) if dur1 > 0 else 0.0
                rel_change_str = f"({rel_change_pct:+.1f}%)"
                diff_str, rel_change_str = colorize_diff(diff_str, rel_change_str)
                diff_display = pad_with_color(diff_str, 12, '>') + " " + rel_change_str
            else:
                diff_display = "NEW" if count2 > 0 else "REMOVED"
                diff_display = f"{diff_display:>12}"
            
            count1_str = f"×{count1}" if count1 > 0 else "---"
            count2_str = f"×{count2}" if count2 > 0 else "---"
            
            print(f"{name:<40} {count1_str:>8} {dur1_str:>15} {pct1:>7.1f}%  {count2_str:>8} {dur2_str:>15} {pct2:>7.1f}%  {diff_display}")
        
        print("-" * 130)
        total_diff = total_dur2 - total_dur1
        total_rel_change = (total_diff / total_dur1 * 100.0) if total_dur1 > 0 else 0.0
        total_diff_str = format_diff(total_diff)
        total_rel_str = f"({total_rel_change:+.1f}%)"
        total_diff_str, total_rel_str = colorize_diff(total_diff_str, total_rel_str)
        total_diff_str = pad_with_color(total_diff_str, 12, '>')
        print(f"{'Total':<40} {'×' + str(total_count1):>8} {format_duration(total_dur1):>15} {(total_dur1/root_duration1*100):>7.1f}%  {'×' + str(total_count2):>8} {format_duration(total_dur2):>15} {(total_dur2/root_duration2*100):>7.1f}%  {total_diff_str} {total_rel_str}")
    else:
        # Non-aggregated comparison
        names1 = {}
        for s in slices1:
            if s.name not in names1:
                names1[s.name] = 0
            names1[s.name] += s.duration_us()
        
        names2 = {}
        for s in slices2:
            if s.name not in names2:
                names2[s.name] = 0
            names2[s.name] += s.duration_us()
        
        all_names = sorted(set(names1.keys()) | set(names2.keys()),
                          key=lambda n: max(names1.get(n, 0), names2.get(n, 0)), reverse=True)
        
        total_dur1 = sum(s.duration_us() for s in slices1)
        total_dur2 = sum(s.duration_us() for s in slices2)
        
        print(f"Comparing slices matching '{pattern}':")
        print(f"Trace 1: {len(slices1)} slices")
        print(f"Trace 2: {len(slices2)} slices")
        print("=" * 120)
        print(f"{'Name':<45} {'Trace 1':>15} {'% Total':>8}  {'Trace 2':>15} {'% Total':>8}  {'Diff':>12}")
        print("-" * 120)
        
        for name in all_names:
            dur1 = names1.get(name, 0)
            dur2 = names2.get(name, 0)
            
            dur1_str = format_duration(dur1) if dur1 > 0 else "---"
            dur2_str = format_duration(dur2) if dur2 > 0 else "---"
            pct1 = (dur1 / root_duration1 * 100.0) if root_duration1 > 0 and dur1 > 0 else 0.0
            pct2 = (dur2 / root_duration2 * 100.0) if root_duration2 > 0 and dur2 > 0 else 0.0
            
            if dur1 > 0 and dur2 > 0:
                diff = dur2 - dur1
                diff_str = format_diff(diff)
                rel_change_pct = (diff / dur1 * 100.0) if dur1 > 0 else 0.0
                rel_change_str = f"({rel_change_pct:+.1f}%)"
                diff_str, rel_change_str = colorize_diff(diff_str, rel_change_str)
                diff_display = pad_with_color(diff_str, 12, '>') + " " + rel_change_str
            else:
                diff_display = "NEW" if dur2 > 0 else "REMOVED"
                diff_display = f"{diff_display:>12}"
            
            print(f"{name:<45} {dur1_str:>15} {pct1:>7.1f}%  {dur2_str:>15} {pct2:>7.1f}%  {diff_display}")
        
        print("-" * 120)
        total_diff = total_dur2 - total_dur1
        total_rel_change = (total_diff / total_dur1 * 100.0) if total_dur1 > 0 else 0.0
        total_diff_str = format_diff(total_diff)
        total_rel_str = f"({total_rel_change:+.1f}%)"
        total_diff_str, total_rel_str = colorize_diff(total_diff_str, total_rel_str)
        total_diff_str = pad_with_color(total_diff_str, 12, '>')
        print(f"{'Total':<45} {format_duration(total_dur1):>15} {(total_dur1/root_duration1*100):>7.1f}%  {format_duration(total_dur2):>15} {(total_dur2/root_duration2*100):>7.1f}%  {total_diff_str} {total_rel_str}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Compare two Perfetto trace files using SQL trace processor."
    )
    parser.add_argument(
        "trace_files",
        nargs=2,
        help="Paths to the two Perfetto trace files to compare."
    )
    parser.add_argument(
        "--parent", "-p",
        help="Root slice name to start from (default: auto-detect longest slice)",
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
    
    trace1_path, trace2_path = args.trace_files
    
    # Load both traces
    print(f"Loading trace 1 from {trace1_path}...")
    tp1, roots1, all_slices1 = load_trace_slices(trace1_path)
    print(f"Found {len(all_slices1)} slices in trace 1.")
    
    print(f"Loading trace 2 from {trace2_path}...")
    tp2, roots2, all_slices2 = load_trace_slices(trace2_path)
    print(f"Found {len(all_slices2)} slices in trace 2.")
    
    # Find roots to display
    if args.parent:
        root1 = find_slice_by_name(roots1, args.parent)
        root2 = find_slice_by_name(roots2, args.parent)
        if not root1 and not root2:
            print(f"Error: Could not find slice named '{args.parent}' in either trace")
            tp1.close()
            tp2.close()
            return
        roots_to_display1 = [root1] if root1 else []
        roots_to_display2 = [root2] if root2 else []
    else:
        # Show ALL roots by default (entire trace)
        roots_to_display1 = roots1
        roots_to_display2 = roots2
    
    # Apply filtering if requested
    if args.filter:
        if args.flat:
            matches1 = []
            for root in roots_to_display1:
                collect_matching_slices(root, args.filter, matches1)
            
            matches2 = []
            for root in roots_to_display2:
                collect_matching_slices(root, args.filter, matches2)
            
            root_dur1 = sum(r.duration_us() for r in roots_to_display1)
            root_dur2 = sum(r.duration_us() for r in roots_to_display2)
            
            print()
            print_flat_comparison(matches1, matches2, args.filter, root_dur1, root_dur2, aggregate=args.aggregate)
            tp1.close()
            tp2.close()
            return
        else:
            filtered1 = []
            for root in roots_to_display1:
                filtered = filter_slice_hierarchy(root, args.filter)
                if filtered:
                    filtered1.append(filtered)
            
            filtered2 = []
            for root in roots_to_display2:
                filtered = filter_slice_hierarchy(root, args.filter)
                if filtered:
                    filtered2.append(filtered)
            
            roots_to_display1 = filtered1
            roots_to_display2 = filtered2
    
    # Display comparison
    mode_parts = []
    if args.aggregate:
        mode_parts.append("Aggregated")
    else:
        mode_parts.append("Detailed")
    
    if args.filter:
        mode_parts.append(f"Filtered: '{args.filter}'")
    
    mode = " - ".join(mode_parts)
    print(f"\nTrace Comparison ({mode}):")
    print("=" * 130)
    header_width = 70 if args.aggregate else 60
    print(f"{'Slice':<{header_width}} {'Trace 1':>20}  {'Trace 2':>20}  {'Diff (abs)':>14} {'Diff (%)':>6}")
    print("-" * 130)
    
    # Compare roots - if multiple roots, compare each
    if not args.filter or not args.flat:
        # Match roots by name for comparison
        roots1_by_name = {r.name: r for r in roots_to_display1}
        roots2_by_name = {r.name: r for r in roots_to_display2}
        all_root_names = sorted(set(roots1_by_name.keys()) | set(roots2_by_name.keys()))
        
        for root_name in all_root_names:
            root1 = roots1_by_name.get(root_name)
            root2 = roots2_by_name.get(root_name)
            
            if args.aggregate and (root1 or root2):
                agg1 = aggregate_slice(root1) if root1 else None
                agg2 = aggregate_slice(root2) if root2 else None
                print_aggregated_comparison(agg1, agg2)
            else:
                print_hierarchy_comparison(root1, root2)
            print()
    
    tp1.close()
    tp2.close()


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        # Happens when piping to head/tail - not an error
        import sys
        sys.stderr.close()
        pass
