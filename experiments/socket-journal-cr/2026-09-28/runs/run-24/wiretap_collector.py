#!/usr/bin/env python3
"""Run the passive observer in the native peer network namespace."""

from datetime import datetime, timezone
from pathlib import Path
import os
import shlex
import subprocess
import sys
import time


TAG = "[CR-DISCOVERY-PROBE-R24]"


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: wiretap_collector.py CONTAINER RAW_DIR")
    container, raw_arg = sys.argv[1:]
    raw = Path(raw_arg).resolve()
    log_path = raw / "wiretap.stdout.log"
    status_path = raw / "wiretap.status"
    command_path = raw / "wiretap.command.txt"
    host_pid_path = raw / "wiretap.host-pid"
    container_pid_path = raw / "wiretap.pid"
    for path in (log_path, status_path, command_path, host_pid_path,
                 container_pid_path, raw / "peer-wire.jsonl"):
        if path.exists():
            raise SystemExit(f"refusing to overwrite {path}")

    script = ("printf '%s\\n' \"$$\" > /run/raw/wiretap.pid; "
              "exec python3 /run/rtps_wire_tap.py /run/raw/peer-wire.jsonl")
    command = ["rtk", "proxy", "docker", "exec", container, "sh", "-c", script]
    command_path.write_text(shlex.join(command) + "\n", encoding="utf-8")
    host_pid_path.write_text(f"collector_pid={os.getpid()}\n", encoding="utf-8")
    start_utc, start_mono = utc_now(), time.monotonic_ns()
    process = subprocess.Popen(command, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True,
                               encoding="utf-8", errors="replace", bufsize=1)
    with log_path.open("x", encoding="utf-8") as log:
        log.write(f"{TAG} host_utc={start_utc} host_mono_ns={start_mono} "
                  f"event=collector_start host_pid={process.pid} container={container}\n")
        log.flush()
        for line in process.stdout:
            stamp_utc, stamp_mono = utc_now(), time.monotonic_ns()
            rendered = (f"{TAG} host_utc={stamp_utc} host_mono_ns={stamp_mono} "
                        f"{line.rstrip()}\n")
            log.write(rendered)
            log.flush()
            print(rendered, end="", flush=True)
        exit_status = process.wait()
        finish_utc, finish_mono = utc_now(), time.monotonic_ns()
        log.write(f"{TAG} host_utc={finish_utc} host_mono_ns={finish_mono} "
                  f"event=collector_exit host_exit_status={exit_status}\n")
        log.flush()
    status_path.write_text(
        f"container={container}\nstart_utc={start_utc}\nstart_mono_ns={start_mono}\n"
        f"finish_utc={finish_utc}\nfinish_mono_ns={finish_mono}\n"
        f"host_exit_status={exit_status}\n", encoding="utf-8")
    return exit_status


if __name__ == "__main__":
    raise SystemExit(main())
