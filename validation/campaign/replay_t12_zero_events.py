#!/usr/bin/env python3
"""Red-capable replay of the retained T12 appcontainer runtime log."""
import importlib.util
import sys
from pathlib import Path

RUNNER = Path(__file__).with_name("run.py")
LOG = Path("/tmp/t12-same/1790933160-d85c852f60/raw/phase-01/checkpoint.log")

spec = importlib.util.spec_from_file_location("campaign_runner", RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

trace_count = 0
metric_lines = 0
max_attempts = 0
for line in LOG.open(encoding="utf-8", errors="replace"):
    parsed = runner.parse_trace_line(line)
    if parsed is None:
        continue
    kind, fields = parsed
    if kind == "trace":
        trace_count += 1
    else:
        metric_lines += 1
        max_attempts = max(max_attempts, fields["attempts"])

print(f"replay={LOG}")
print(f"parsed_metrics={metric_lines} max_attempts={max_attempts} parsed_trace_events={trace_count}")
if metric_lines and max_attempts > 0 and trace_count == 0:
    print("RED: actual capture has trace activity metrics but no RTPS_TRACE event records")
    sys.exit(1)
print("GREEN: symptom absent or capture lacks activity; replay inconclusive")
