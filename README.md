# jolt-perfetto

Usage

```zsh
python summarise_traces.py trace-small.json trace-large.json trace-small_b.json -p "Stage 3 sumchecks" -s time_1
```

```zsh
python compare_traces.py trace-small.json trace-large.json -p "Stage 3 sumchecks" -s diff
```

A python tool used to analysis Perfetto traces to identify bottlenecks in Jolt run time
