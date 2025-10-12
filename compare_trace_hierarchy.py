#!/usr/bin/env python3
"""
compare_trace_hierarchy.py
Compare two Perfetto trace JSON files and display side-by-side hierarchy
with timing differences.

Usage:
    python compare_trace_hierarchy.py trace1.json trace2.json [-p "Root Slice Name"] [-a] [-f PATTERN] [--flat]

Options:
    -p, --parent        Root slice name to start from (default: auto-detect longest slice)
    -a, --aggregate     Aggregate repeated function calls and show counts
    -f, --filter        Filter slices by pattern (e.g., '*::bind', 'compute_*')
    --flat              Show flat list of matches instead of hierarchy (use with --filter)

Examples:
    # Compare full hierarchies
    python compare_trace_hierarchy.py trace1.json trace2.json
    
    # Compare aggregated views
    python compare_trace_hierarchy.py trace1.json trace2.json -a
    
    # Compare only slices matching pattern
    python compare_trace_hierarchy.py trace1.json trace2.json -f "*::bind"
    
    # Flat comparison of matching slices
    python compare_trace_hierarchy.py trace1.json trace2.json -f "*::bind" --flat
    
    # Combine options
    python compare_trace_hierarchy.py trace1.json trace2.json -p "Stage 3" -f "*compute*" -a
"""

import json
import argparse
import fnmatch
import re
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
    """Find a slice by name in the hierarchy."""
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
    """Format duration in the most appropriate unit."""
    if duration_us >= 1_000_000:  # >= 1 second
        return f"{duration_us / 1_000_000:.3f}s"
    elif duration_us >= 1_000:  # >= 1 millisecond
        return f"{duration_us / 1_000:.3f}ms"
    else:  # microseconds
        return f"{duration_us:.1f}µs"


def format_diff(diff_us: float) -> str:
    """Format duration difference with +/- sign."""
    sign = "+" if diff_us >= 0 else ""
    return sign + format_duration(abs(diff_us))


def visible_length(s: str) -> int:
    """Calculate visible length of string, excluding ANSI color codes."""
    # Remove ANSI escape sequences
    ansi_escape = re.compile(r'\033\[[0-9;]*m')
    return len(ansi_escape.sub('', s))


def pad_with_color(s: str, width: int, align: str = '>') -> str:
    """
    Pad a string that may contain ANSI color codes.
    
    Args:
        s: String to pad (may contain ANSI codes)
        width: Desired visible width
        align: Alignment ('>' for right, '<' for left, '^' for center)
    """
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
    """
    Add color coding to difference strings.
    Red for slower (positive), green for faster (negative).
    
    Returns: (colored_diff_str, colored_rel_change_str)
    """
    # ANSI color codes
    RED = '\033[91m'
    GREEN = '\033[92m'
    RESET = '\033[0m'
    
    # Determine color based on the sign
    if diff_str.startswith('+') and diff_str not in ["NEW", "REMOVED"]:
        color = RED  # Slower is bad (red)
    elif diff_str.startswith('-'):
        color = GREEN  # Faster is good (green)
    else:
        color = ''  # No change or special case
    
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


def filter_slice_hierarchy(slice_obj: TraceSlice, pattern: str) -> Optional[TraceSlice]:
    """Filter a slice hierarchy to only include slices matching the pattern."""
    this_matches = matches_pattern(slice_obj.name, pattern)
    
    filtered_children = []
    for child in slice_obj.children:
        filtered_child = filter_slice_hierarchy(child, pattern)
        if filtered_child:
            filtered_children.append(filtered_child)
    
    if this_matches or filtered_children:
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
    """Collect all slices matching the pattern into a flat list."""
    if matches_pattern(slice_obj.name, pattern):
        matches.append(slice_obj)
    
    for child in slice_obj.children:
        collect_matching_slices(child, pattern, matches)


def aggregate_slice(slice_obj: TraceSlice) -> AggregatedSlice:
    """Create an aggregated view of a slice hierarchy."""
    agg = AggregatedSlice(slice_obj.name)
    agg.add_slice(slice_obj)
    return agg


def print_hierarchy_comparison(slice1: Optional[TraceSlice], slice2: Optional[TraceSlice],
                               parent_duration1: Optional[float] = None,
                               parent_duration2: Optional[float] = None,
                               prefix: str = "", is_last: bool = True):
    """Print side-by-side comparison of two hierarchies."""
    # Handle cases where slice exists in only one trace
    if slice1 is None and slice2 is None:
        return
    
    name = slice1.name if slice1 else slice2.name
    
    # Calculate percentages
    if slice1:
        if parent_duration1 is None:
            parent_duration1 = slice1.duration
            pct1 = 100.0
        else:
            pct1 = (slice1.duration / parent_duration1 * 100.0) if parent_duration1 > 0 else 0.0
        dur1_str = format_duration(slice1.duration)
    else:
        pct1 = 0.0
        dur1_str = "---"
    
    if slice2:
        if parent_duration2 is None:
            parent_duration2 = slice2.duration
            pct2 = 100.0
        else:
            pct2 = (slice2.duration / parent_duration2 * 100.0) if parent_duration2 > 0 else 0.0
        dur2_str = format_duration(slice2.duration)
    else:
        pct2 = 0.0
        dur2_str = "---"
    
    # Calculate difference
    if slice1 and slice2:
        diff = slice2.duration - slice1.duration
        diff_str = format_diff(diff)
        # Calculate relative change as percentage
        rel_change_pct = (diff / slice1.duration * 100.0) if slice1.duration > 0 else 0.0
        rel_change_str = f"{rel_change_pct:+.1f}%"
        # Apply color coding
        diff_str, rel_change_str = colorize_diff(diff_str, rel_change_str)
        # Pad after coloring
        diff_str = pad_with_color(diff_str, 12, '>')
        rel_change_str = pad_with_color(rel_change_str, 8, '>')
    else:
        diff_str = "NEW" if slice2 and not slice1 else "REMOVED"
        rel_change_str = ""
        diff_str = f"{diff_str:>12}"
        rel_change_str = f"{rel_change_str:>8}"
    
    # Tree formatting with fixed-width name column
    connector = "└─ " if is_last else "├─ "
    # Calculate padding needed to reach fixed column width (60 chars total for name+tree)
    name_col_width = 60
    current_length = len(prefix) + len(connector) + len(name)
    padding = max(1, name_col_width - current_length)
    
    print(f"{prefix}{connector}{name}{' ' * padding}{dur1_str:>12} ({pct1:>5.1f}%)  {dur2_str:>12} ({pct2:>5.1f}%)  {diff_str} {rel_change_str}")
    
    # Prepare prefix for children
    if is_last:
        child_prefix = prefix + "   "
    else:
        child_prefix = prefix + "│  "
    
    # Match children by name and recurse
    children1 = {c.name: c for c in (slice1.children if slice1 else [])}
    children2 = {c.name: c for c in (slice2.children if slice2 else [])}
    all_child_names = sorted(set(children1.keys()) | set(children2.keys()))
    
    for i, child_name in enumerate(all_child_names):
        is_last_child = (i == len(all_child_names) - 1)
        child1 = children1.get(child_name)
        child2 = children2.get(child_name)
        print_hierarchy_comparison(
            child1, child2,
            slice1.duration if slice1 else None,
            slice2.duration if slice2 else None,
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
        # Calculate relative change as percentage
        rel_change_pct = (diff / agg1.total_duration * 100.0) if agg1.total_duration > 0 else 0.0
        rel_change_str = f"{rel_change_pct:+.1f}%"
        # Apply color coding
        diff_str, rel_change_str = colorize_diff(diff_str, rel_change_str)
        # Pad after coloring
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
    
    # Tree formatting with fixed-width columns
    connector = "└─ " if is_last else "├─ "
    name_with_count = f"{name} {count1_str:>6} {count2_str:>6} {count_diff_str}"
    
    # Calculate padding for fixed column width (70 chars total for name+tree+counts)
    name_col_width = 70
    current_length = len(prefix) + len(connector) + len(name_with_count)
    padding = max(1, name_col_width - current_length)
    
    print(f"{prefix}{connector}{name_with_count}{' ' * padding}{dur1_str:>12} ({pct1:>5.1f}%)  {dur2_str:>12} ({pct2:>5.1f}%)  {diff_str} {rel_change_str}")
    
    # Prepare prefix for children
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


def print_flat_comparison(slices1: List[TraceSlice], slices2: List[TraceSlice],
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
            agg1[s.name] = (count + 1, dur + s.duration)
        
        agg2: Dict[str, Tuple[int, float]] = {}
        for s in slices2:
            if s.name not in agg2:
                agg2[s.name] = (0, 0.0)
            count, dur = agg2[s.name]
            agg2[s.name] = (count + 1, dur + s.duration)
        
        all_names = sorted(set(agg1.keys()) | set(agg2.keys()))
        
        total_dur1 = sum(s.duration for s in slices1)
        total_dur2 = sum(s.duration for s in slices2)
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
                # Apply color
                diff_str, rel_change_str = colorize_diff(diff_str, rel_change_str)
                # Create display with proper spacing (not using f-string padding after color)
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
        # Non-aggregated: match individual slices
        # For simplicity, just list all from each trace
        print(f"Comparing slices matching '{pattern}':")
        print(f"Trace 1: {len(slices1)} slices")
        print(f"Trace 2: {len(slices2)} slices")
        print("=" * 120)
        print(f"{'Name':<45} {'Trace 1':>15} {'% Total':>8}  {'Trace 2':>15} {'% Total':>8}  {'Diff':>12}")
        print("-" * 120)
        
        # Aggregate for simpler comparison even in non-aggregate mode
        names1 = {}
        for s in slices1:
            if s.name not in names1:
                names1[s.name] = 0
            names1[s.name] += s.duration
        
        names2 = {}
        for s in slices2:
            if s.name not in names2:
                names2[s.name] = 0
            names2[s.name] += s.duration
        
        all_names = sorted(set(names1.keys()) | set(names2.keys()),
                          key=lambda n: max(names1.get(n, 0), names2.get(n, 0)), reverse=True)
        
        total_dur1 = sum(slices1[i].duration for i in range(len(slices1)))
        total_dur2 = sum(slices2[i].duration for i in range(len(slices2)))
        
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
                # Apply color
                diff_str, rel_change_str = colorize_diff(diff_str, rel_change_str)
                # Create display with proper spacing
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
        description="Compare two Perfetto trace files side-by-side."
    )
    parser.add_argument(
        "trace_files",
        nargs=2,
        help="Paths to the two Perfetto JSON trace files to compare."
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
    
    # Parse both trace files
    print(f"Parsing {trace1_path}...")
    slices1 = parse_perfetto_json(trace1_path)
    print(f"Found {len(slices1)} slices in trace 1.")
    
    print(f"Parsing {trace2_path}...")
    slices2 = parse_perfetto_json(trace2_path)
    print(f"Found {len(slices2)} slices in trace 2.")
    
    # Build hierarchies
    print("Building hierarchies...")
    roots1 = build_hierarchy(slices1)
    roots2 = build_hierarchy(slices2)
    
    # Find roots to display
    if args.parent:
        root1 = find_slice_by_name(roots1, args.parent)
        root2 = find_slice_by_name(roots2, args.parent)
        if not root1 and not root2:
            print(f"Error: Could not find slice named '{args.parent}' in either trace")
            return
        roots_to_display1 = [root1] if root1 else []
        roots_to_display2 = [root2] if root2 else []
    else:
        # Auto-detect: use longest root slices
        roots_to_display1 = sorted(roots1, key=lambda s: s.duration, reverse=True)[:1] if roots1 else []
        roots_to_display2 = sorted(roots2, key=lambda s: s.duration, reverse=True)[:1] if roots2 else []
    
    # Apply filtering if requested
    if args.filter:
        if args.flat:
            # Flat view: collect all matching slices
            matches1 = []
            for root in roots_to_display1:
                collect_matching_slices(root, args.filter, matches1)
            
            matches2 = []
            for root in roots_to_display2:
                collect_matching_slices(root, args.filter, matches2)
            
            root_dur1 = sum(r.duration for r in roots_to_display1)
            root_dur2 = sum(r.duration for r in roots_to_display2)
            
            print()
            print_flat_comparison(matches1, matches2, args.filter, root_dur1, root_dur2, aggregate=args.aggregate)
            return
        else:
            # Hierarchical view: filter the trees
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
    # Header with better alignment for fixed-width columns
    header_width = 70 if args.aggregate else 60
    print(f"{'Slice':<{header_width}} {'Trace 1':>20}  {'Trace 2':>20}  {'Diff (abs)':>14} {'Diff (%)':>6}")
    print("-" * 130)
    
    # Compare roots
    root1 = roots_to_display1[0] if roots_to_display1 else None
    root2 = roots_to_display2[0] if roots_to_display2 else None
    
    if args.aggregate and root1:
        agg1 = aggregate_slice(root1)
        agg2 = aggregate_slice(root2) if root2 else None
        print_aggregated_comparison(agg1, agg2)
    else:
        print_hierarchy_comparison(root1, root2)
    
    print()


if __name__ == "__main__":
    main()
