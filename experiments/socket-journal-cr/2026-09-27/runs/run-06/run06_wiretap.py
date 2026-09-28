#!/usr/bin/env python3
"""Run the reviewed passive RTPS observer with a run-06-specific log tag."""

import runpy
import sys


observer = runpy.run_path(
    "/repo/experiments/socket-journal-cr/2026-09-27/runs/run-04/rtps_wire_tap.py",
    run_name="run06_wiretap_reference",
)
observer["main"].__globals__["TAG"] = "[CR-RUN06-WIRETAP]"
raise SystemExit(observer["main"]())
