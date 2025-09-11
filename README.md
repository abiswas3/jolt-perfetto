# jolt-perfetto

Download the [trace_processor shell](https://perfetto.dev/docs/analysis/trace-processor)

````zsh
# Download prebuilts (Linux and Mac only)
curl -LO https://get.perfetto.dev/trace_processor
chmod +x ./trace_processor
Usage

```zsh
python summarise_traces.py trace-small.json trace-large.json trace-small_b.json -p "Stage 3 sumchecks" -s time_1
````

```zsh
python compare_traces.py trace-small.json trace-large.json -p "Stage 3 sumchecks" -s diff
```

A python tool used to analysis Perfetto traces to identify bottlenecks in Jolt run time
