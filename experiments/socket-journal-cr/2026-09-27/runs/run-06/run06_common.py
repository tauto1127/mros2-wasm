#!/usr/bin/env python3
"""Shared paths and small helpers for the local Docker run-06 experiment."""

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import subprocess
import time


TAG = "[CR-RUN06]"
RUN_DIR = Path(__file__).resolve().parent
RAW = RUN_DIR / "raw"
ROOT = RUN_DIR.parents[4]
TMP_ROOT = Path("/tmp/mros2-wasm-cr-run06")
STATE = TMP_ROOT / "state"
NETWORK = "mros2-cr-net"
IMAGE = "ros:humble"
IMAGE_ID = "sha256:1813d3c85d7f96ff7d3012d865204583255740182db5d0065f8f8cd029a83138"
RUNTIME_DIR = Path("/tmp/mros2-wasm-cr-rerun-20260927/runtime")
APP_DIR = Path("/tmp/mros2-wasm-cr-rerun-20260927/app")
IWASM = RUNTIME_DIR / "iwasm"
WASM = APP_DIR / "echoback_string.wasm"
PEER = Path("/tmp/mros2-posix-run04-final-build/mros2-posix")
REFERENCE_WIRETAP = ROOT / "experiments/socket-journal-cr/2026-09-27/runs/run-04/rtps_wire_tap.py"
EXPECTED_HASHES = {
    IWASM: "96c9f1ae89a29e8b2ab87eccdb54df4f7e6203be6945413cc19052df09f3920a",
    WASM: "0a725f9a303650a64358964a6f6ef0cd84d5cc82734fcbeb87ec8f7dd1d8df76",
    PEER: "8f41fa890a8da84c9000772bba2fb8287553bea1311ccf7fd4d5d0daed7b27b1",
}
CONTAINERS = {
    "source": "mros2-cr-run06-source",
    "peer": "mros2-cr-run06-native-peer",
    "destination": "mros2-cr-run06-destination",
    "wiretap": "mros2-cr-run06-wiretap",
}
LABEL_KEY = "io.mros2-cr.run"
LABEL_VALUE = "run-06"


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def mono_ns():
    return time.monotonic_ns()


def rtk(args, *, timeout=None):
    return subprocess.run(
        ["rtk", "proxy", *map(str, args)], check=False, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=timeout,
    )


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_new(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(content)


def docker(*args, timeout=None):
    return rtk(["docker", *args], timeout=timeout)

