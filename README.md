
# Perfetto Trace Analyzer

Command-line tools to analyze and compare Perfetto trace JSON files with hierarchical visualization.

## Tools

### 1. `analyze_trace.py` - Single Trace Analysis
Analyze one trace file and visualize timing hierarchies.

### 2. `compare_trace_hierarchy.py` - Side-by-Side Comparison
Compare two trace files and show timing differences.

## Features

- 📊 **Hierarchical visualization** of trace slices with timing and percentages
- 🔢 **Aggregation mode** to group repeated function calls
- 🔍 **Pattern filtering** to focus on specific slices (e.g., `*::bind`)
- 📋 **Flat list view** for sorted analysis
- 🎯 **Parent selection** to analyze specific subtrees
- ⚖️ **Side-by-side comparison** with difference calculations

## Installation

No installation required! Just Python 3.6+

```bash
# Make the script executable (optional)
chmod +x analyze_trace.py
```

## Usage

### Single Trace Analysis (`analyze_trace.py`)

```bash
python3 analyze_trace.py TRACE_FILE [OPTIONS]
```

### Two Trace Comparison (`compare_trace_hierarchy.py`)

```bash
python3 compare_trace_hierarchy.py TRACE1 TRACE2 [OPTIONS]
```

### Basic Examples

#### Single Trace

**1. Analyze full trace (auto-detect root):**
```bash
python3 analyze_trace.py test.json
```

**2. Start from specific parent slice:**
```bash
python3 analyze_trace.py test.json -p "Stage 3 sumchecks"
```

**3. Show aggregated view with call counts:**
```bash
python3 analyze_trace.py test.json -a
```

#### Comparison

**4. Compare two traces:**
```bash
python3 compare_trace_hierarchy.py trace1.json trace2.json
```

**5. Compare with aggregation:**
```bash
python3 compare_trace_hierarchy.py trace1.json trace2.json -a
```

**6. Compare specific parent slices:**
```bash
python3 compare_trace_hierarchy.py trace1.json trace2.json -p "Stage 2"
```

### Filtering Examples

#### Single Trace

**4. Show only slices matching a pattern (hierarchical):**
```bash
python3 analyze_trace.py test.json -f "*::bind"
```

**5. Flat list of all matching slices:**
```bash
python3 analyze_trace.py test.json -f "*::bind" --flat
```

**6. Aggregated flat list (grouped by name with counts):**
```bash
python3 analyze_trace.py test.json -f "*::bind" --flat -a
```

#### Comparison

**7. Compare only matching slices:**
```bash
python3 compare_trace_hierarchy.py trace1.json trace2.json -f "*::bind"
```

**8. Flat comparison of matching slices:**
```bash
python3 compare_trace_hierarchy.py trace1.json trace2.json -f "*::bind" --flat
```

**9. Aggregated flat comparison:**
```bash
python3 compare_trace_hierarchy.py trace1.json trace2.json -f "*::bind" --flat -a
```

### Combined Examples

#### Single Trace

**7. Find all compute functions under Stage 2:**
```bash
python3 analyze_trace.py test.json -p "Stage 2" -f "compute_*"
```

**8. Aggregated analysis of binds in Stage 3:**
```bash
python3 analyze_trace.py test.json -p "Stage 3 sumchecks" -f "*::bind" -a
```

**9. Flat aggregated list of prover messages:**
```bash
python3 analyze_trace.py test.json -f "*prover_message*" --flat -a
```

#### Comparison

**10. Compare Stage 3 between two traces:**
```bash
python3 compare_trace_hierarchy.py trace1.json trace2.json -p "Stage 3"
```

**11. Compare all binds with aggregation:**
```bash
python3 compare_trace_hierarchy.py trace1.json trace2.json -f "*::bind" -a
```

**12. Flat aggregated comparison of compute functions in Stage 2:**
```bash
python3 compare_trace_hierarchy.py trace1.json trace2.json -p "Stage 2" -f "compute_*" --flat -a
```

## Options

| Option | Short | Description |
|--------|-------|-------------|
| `--parent NAME` | `-p` | Start analysis from slice named NAME (default: auto-detect longest slice) |
| `--aggregate` | `-a` | Group repeated function calls and show counts |
| `--filter PATTERN` | `-f` | Filter slices by glob pattern (e.g., `*::bind`, `compute_*`) |
| `--flat` | | Show flat sorted list instead of hierarchy (use with `--filter`) |

## Pattern Syntax

Patterns use glob-style matching:

- `*::bind` - Any slice ending with "::bind"
- `compute_*` - Any slice starting with "compute_"
- `*prover*` - Any slice containing "prover"
- `Stage?` - "Stage" followed by any single character
- `DensePolynomial::*` - Any slice in the DensePolynomial namespace

## Output Format

### Hierarchical View

```
└─ Root (10.500s, 100.0%)
   ├─ A (8.000s, 76.2%)
   │  ├─ A1 (7.200s, 90.0%)
   │  └─ A2 (0.800s, 10.0%)
   └─ B (2.000s, 19.0%)
```

- **Duration**: Time in seconds (s), milliseconds (ms), or microseconds (µs)
- **Percentage**: Relative to immediate parent's duration

### Aggregated Hierarchical View (`-a`)

```
└─ Root (10.500s, 100.0%)
   ├─ compute_prover_message [×4] (104.0µs, 15.2%)
   └─ bind [×3] (85.0µs, 12.4%)
```

- **[×N]**: Function was called N times
- **Duration**: Total time across all calls
- **Percentage**: Total time relative to parent

### Flat List View (`--flat`)

```
Found 15 slices matching '*::bind':
====================================================================================================
Name                                          Duration   % of Matches    % of Total
----------------------------------------------------------------------------------------------------
OneHotPolynomialProverOpening::bind             35.0µs         41.2%          2.1%
DensePolynomial::bind                           28.0µs         32.9%          1.7%
GruenSplitEqPolynomial::bind                     1.6µs          1.9%          0.1%
----------------------------------------------------------------------------------------------------
Total                                           85.0µs        100.0%          5.2%
```

- **% of Matches**: Percentage of time among all filtered slices
- **% of Total**: Percentage of total trace/root time

### Aggregated Flat List View (`--flat -a`)

```
Found 3 unique slices matching '*::bind' (15 total calls):
==============================================================================================================
Name                                          Count    Duration   % of Matches    % of Total
--------------------------------------------------------------------------------------------------------------
OneHotPolynomialProverOpening::bind              ×5      175.0µs         58.3%          1.8%
DensePolynomial::bind                            ×8      120.0µs         40.0%          1.2%
GruenSplitEqPolynomial::bind                     ×2        5.0µs          1.7%          0.05%
--------------------------------------------------------------------------------------------------------------
Total                                           ×15      300.0µs        100.0%          3.0%
```

- **Count**: Total number of calls for this slice name
- **Duration**: Total time across all calls
- **% of Matches/Total**: Same as flat list view

## Comparison Output Formats

### Hierarchical Comparison

```
Trace Comparison (Detailed):
================================================================================================================================
Slice                                     Trace 1                   Trace 2                   Difference
--------------------------------------------------------------------------------------------------------------------------------
└─ Root                                    10.000s (100.0%)          12.000s (100.0%)          +2.000s   +0.0%
   ├─ Stage 1                              3.000s ( 30.0%)           2.500s ( 20.8%)          -0.500s  -9.2%
   │  └─ compute_prover_message            2.500s ( 83.3%)           2.000s ( 80.0%)          -0.500s  -3.3%
   └─ Stage 2                              7.000s ( 70.0%)           9.500s ( 79.2%)          +2.500s  +9.2%
```

- Shows slices side-by-side with durations and percentages
- **Difference**: Absolute time difference (Trace 2 - Trace 1)
- **Percentage Diff**: Change in percentage of parent  
- **NEW/REMOVED**: Slices that appear in only one trace

### Aggregated Hierarchical Comparison (`-a`)

```
Slice                                     Trace 1                   Trace 2                   Difference
--------------------------------------------------------------------------------------------------------------------------------
└─ bind   [×15] [×18] (+3)                0.850s (  8.5%)           1.050s (  8.8%)          +0.200s  +0.3%
   ├─ DensePolynomial::bind   [×8]  [×10] (+2)
   │                                       0.600s ( 70.6%)           0.750s ( 71.4%)          +0.150s  +0.8%
   └─ OneHotPolynomial::bind  [×7]  [×8]  (+1)
                                           0.250s ( 29.4%)           0.300s ( 28.6%)          +0.050s  -0.8%
```

- **[×N]**: Call count in each trace
- **(+N)/(-N)**: Change in call count between traces

### Flat Comparison (`--flat`)

```
Comparing slices matching '*::bind':
Trace 1: 15 slices  |  Trace 2: 18 slices
================================================================================================================================
Name                                          Trace 1            % Total     Trace 2            % Total     Diff
--------------------------------------------------------------------------------------------------------------------------------
DensePolynomial::bind                          600.0µs             6.0%       750.0µs             6.2%    +150.0µs
OneHotPolynomial::bind                         250.0µs             2.5%       300.0µs             2.5%     +50.0µs
--------------------------------------------------------------------------------------------------------------------------------
Total                                          850.0µs             8.5%      1050.0µs             8.8%    +200.0µs
```

### Aggregated Flat Comparison (`--flat -a`)

```
Comparing slices matching '*::bind':
Trace 1: 3 unique (15 total calls)  |  Trace 2: 4 unique (18 total calls)
====================================================================================================================================
Name                                          Count    Trace 1        % Total     Count    Trace 2        % Total     Diff
------------------------------------------------------------------------------------------------------------------------------------
DensePolynomial::bind                            ×8     600.0µs         6.0%        ×10     750.0µs         6.2%    +150.0µs
OneHotPolynomial::bind                           ×7     250.0µs         2.5%         ×8     300.0µs         2.5%     +50.0µs
------------------------------------------------------------------------------------------------------------------------------------
Total                                           ×15     850.0µs         8.5%        ×18    1050.0µs         8.8%    +200.0µs
```

- **Count**: Number of calls in each trace
- **Diff**: Positive = slower in Trace 2, Negative = faster in Trace 2

## Input Format

Supports Perfetto JSON trace files in two formats:

**Format 1: Wrapped**
```json
{
  "traceEvents": [
    {"name": "foo", "ph": "B", "ts": 1000, "pid": 1, "tid": 1},
    {"name": "foo", "ph": "E", "ts": 2000, "pid": 1, "tid": 1}
  ]
}
```

**Format 2: Direct array**
```json
[
  {"name": "foo", "ph": "B", "ts": 1000, "pid": 1, "tid": 1},
  {"name": "foo", "ph": "E", "ts": 2000, "pid": 1, "tid": 1}
]
```

Supports both:
- Duration events (`ph: 'X'` with `dur`)
- Begin/End pairs (`ph: 'B'` and `ph: 'E'`)

## Tips

1. **Start broad, then narrow**: Run without filters first to see the full hierarchy, then use `-f` to zoom in
2. **Use `-a` for overview**: Aggregation is great for seeing patterns in repeated calls
3. **Combine `-p` and `-f`**: Analyze specific sections with targeted filtering
4. **Use `--flat -a` for summaries**: Perfect for quick "what's taking time?" answers

## Coming Soon

- **`compare_trace_hierarchy.py`** - Side-by-side comparison of two trace files
- Support for Perfetto SQL queries
- Export to CSV/JSON
- Performance regression detection

## Technical Details

- **No external dependencies** beyond Python 3.6+ standard library
- **Direct JSON parsing** (not using Perfetto trace processor)
- **Hierarchy built from timestamp containment** - a slice is a parent if it completely contains another slice on the same thread

## Troubleshooting

**"No slices found"**: Check that your JSON file contains trace events with timing information (`ts`, `dur`, or `ph: 'B'/'E'`)

**"Could not find slice named 'X'"**: The parent name is case-sensitive and must match exactly. Run without `-p` to see available slice names.

**Wrong hierarchy**: Ensure slices have correct `pid` and `tid` - slices are only nested if they're on the same process and thread.

## Contributing

Feel free to extend this tool! Some ideas:
- Add more output formats (CSV, JSON, HTML)
- Integration with Perfetto's trace processor
- Statistical analysis (mean, median, std dev for repeated calls)
- Flame graph generation

## License

MIT License - use freely!
