#!/usr/bin/env python3
"""Validate a complete observer file emitted by the real WASI trace app.

Pass the append log captured from the SDK-built app running under the pinned
WAMR iwasm runtime. This deliberately does not manufacture observer records.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import importlib.util

RUNNER = Path(__file__).with_name("run.py")
spec = importlib.util.spec_from_file_location("trace_channel_runner", RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def validate(path: Path) -> dict[str, int]:
    data = path.read_bytes()
    if not data or not data.endswith(b"\n"):
        raise AssertionError("actual observer output is empty or has an unterminated final record")
    if b"\\n" in data:
        raise AssertionError("observer output contains a literal backslash-n record terminator")
    lines = data.splitlines()
    if any(not line for line in lines):
        raise AssertionError("observer output contains an empty physical record")

    parsed = runner.parse_observer_channel(data)
    if parsed["errors"]:
        raise AssertionError("strict production parser rejected actual WASI output: " + parsed["errors"][0])
    windows = [value for kind, value in parsed["records"] if kind == "window_start"]
    guest = [value for kind, value in parsed["records"] if kind == "guest_state"]
    batches = parsed["batches"]
    events = [event for batch in batches for event in batch["events"]]
    metrics = [row for batch in batches for row in batch["metrics"]]
    if not windows or not batches or not events or not metrics:
        raise AssertionError("actual output lacks a WINDOW_START, batch, event, or metrics record")
    parts = {record.get("part") for record in guest}
    if not {"c", "cpp"}.issubset(parts):
        raise AssertionError(f"actual C/C++ guest-state records missing: {parts}")
    for record in guest:
        json.dumps(record, allow_nan=False)
        if record.get("schema") != "guest-state-v1;actual wasm32 addresses + copied values;raw memory little-endian;IPv4 semantic bytes network-order":
            raise AssertionError("actual guest-state JSON has unexpected schema")
    for batch in batches:
        if len(batch["metrics"]) != 2 or len(batch["events"]) != batch["end"].get("events"):
            raise AssertionError("actual batch is incomplete or truncated")
        for snapshot in batch["metrics"]:
            if not all(isinstance(snapshot.get(key), int) for key in
                       ("read", "next", "attempts", "winners", "busy", "failed", "outcomes",
                        "probe_completions", "active", "max_active", "lost", "output_failures",
                        "lockfree", "addr_read", "addr_next", "addr_attempts", "addr_winners",
                        "addr_busy", "addr_failed", "addr_outcomes", "addr_probe_completions",
                        "addr_active", "addr_max_active", "addr_lost", "addr_output_failures",
                        "addr_lockfree")):
                raise AssertionError("actual metrics snapshot lacks emitted values or counter addresses")
    return {"physical_lines": len(lines), "window_starts": len(windows),
            "batches": len(batches), "events": len(events), "metrics": len(metrics),
            "guest_c": sum(record.get("part") == "c" for record in guest),
            "guest_cpp": sum(record.get("part") == "cpp" for record in guest)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("observer_log", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(args.observer_log), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
