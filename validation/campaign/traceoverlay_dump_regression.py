#!/usr/bin/env python3
"""Compile and run the retained ring + actual ProjectionTraceBatch dump seam."""
from __future__ import annotations
import importlib.util
import os
import re
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OVERLAY_DIR = Path(os.environ.get(
    "TRACE_OVERLAY_DIR", "/tmp/mros2-trace-build-evidence-20261002/overlay"))
SEDP = OVERLAY_DIR / "SEDPAgent.cpp"
HEADER = OVERLAY_DIR / "traceoverlay.h"
RING = OVERLAY_DIR / "traceoverlay.c"
RUNNER_PATH = HERE / "run.py"
BUILDER_PATH = HERE / "build_trace_app.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = load_module("campaign_runner", RUNNER_PATH)
builder = load_module("trace_app_builder", BUILDER_PATH)
source = SEDP.read_text()
fixed = builder.correct_trace_dump(source)
assert source.count("traceoverlay_drain(") == 2, "expected retained defective v6 dump"
assert fixed.count("traceoverlay_drain(") == 1, "builder did not leave one consuming drain"
assert fixed.index("traceoverlay_init();", fixed.index("~ProjectionTraceBatch")) < fixed.index(
    "traceoverlay_record(", fixed.index("~ProjectionTraceBatch")), "init must precede record"

start_token = "namespace {\nstruct ProjectionTraceBatch"
end_token = "\nbool SEDPAgent::init"

def extract_batch(text: str) -> str:
    start = text.index(start_token)
    end = text.index(end_token, start)
    return text[start:end]

preamble = f'''#include <cstdint>
#include <cstdio>
#include <pthread.h>
#include "{HEADER}"
'''
main = '''
int main() {
  ProjectionTraceBatch batch;
  batch.add(TRACE_TRYLOCK_ATTEMPT, 0x01020304u, 0x05060708u);
  batch.add(TRACE_TRYLOCK_OUTCOME, 0x11223344u, 0x55667788u);
  return 0;
}
'''
expected = [(2, 0x01020304, 0x05060708), (3, 0x11223344, 0x55667788)]
trace_re = re.compile(r"RTPS_TRACE seq=(\d+) kind=(\d+) result=(\d+) current=(\d+) applied=(\d+) detail=(\d+) aux=(\d+) thread=(\d+)")


def compile_and_run(directory: Path, name: str, overlay_source: str) -> str:
    cpp = directory / f"{name}.cpp"
    binary = directory / name
    cpp.write_text(preamble + extract_batch(overlay_source) + main)
    subprocess.run([os.environ.get("CC", "cc"), "-std=c11", "-I", str(OVERLAY_DIR),
                    "-c", str(RING), "-o", str(directory / f"{name}-ring.o")], check=True)
    subprocess.run([os.environ.get("CXX", "c++"), "-std=c++17", "-I", str(OVERLAY_DIR),
                    str(cpp), str(directory / f"{name}-ring.o"), "-pthread", "-o", str(binary)], check=True)
    return subprocess.run([str(binary)], check=True, text=True, capture_output=True).stdout


def parse_output(text: str):
    events = []
    metrics = []
    for line in text.splitlines():
        parsed = runner.parse_trace_line(line)
        if parsed is None:
            continue
        kind, fields = parsed
        if kind == "trace":
            events.append(fields)
        else:
            metrics.append(fields)
    return events, metrics


with tempfile.TemporaryDirectory(prefix="t12-trace-dump-") as temp:
    temp_path = Path(temp)
    old_output = compile_and_run(temp_path, "old", source)
    fixed_output = compile_and_run(temp_path, "fixed", fixed)
    old_events, old_metrics = parse_output(old_output)
    events, metrics = parse_output(fixed_output)
    assert len(old_metrics) == 1 and old_metrics[0]["attempts"] == 1
    assert old_metrics[0]["winners"] == 1 and old_metrics[0]["outcomes"] == 1
    assert old_metrics[0]["lost"] == 0 and old_metrics[0]["lockfree"] == 1
    assert not old_events, "old actual dump should reproduce zero event rows"
    assert len(metrics) == 1
    assert metrics[0]["attempts"] == metrics[0]["winners"] == metrics[0]["outcomes"] == 1
    assert metrics[0]["busy"] == metrics[0]["failed"] == metrics[0]["active"] == 0
    assert metrics[0]["lost"] == 0 and metrics[0]["lockfree"] == 1
    assert [(e["kind"], e["current_ip"], e["applied_ip"]) for e in events] == expected
    assert all(e["thread_id"] > 0 for e in events)
    print(f"OLD_RED events={len(old_events)} attempts={old_metrics[0]['attempts']} winners={old_metrics[0]['winners']} lost={old_metrics[0]['lost']}")
    print(f"FIXED_GREEN events={len(events)} parsed_values={[(e['kind'], e['current_ip'], e['applied_ip'], e['thread_id']) for e in events]} attempts={metrics[0]['attempts']} winners={metrics[0]['winners']} outcomes={metrics[0]['outcomes']} lost={metrics[0]['lost']} lockfree={metrics[0]['lockfree']}")
