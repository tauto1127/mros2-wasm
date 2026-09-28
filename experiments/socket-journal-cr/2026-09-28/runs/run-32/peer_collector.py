#!/usr/bin/env python3
"""Capture native peer stdout with host UTC and monotonic timestamps."""

from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
import sys
import time


TAG = "[SEDP-RACE-RUN32]"


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: peer_collector.py CONTAINER RAW_DIR")
    container, raw_arg = sys.argv[1:]
    raw = Path(raw_arg).resolve()
    log_path = raw / "peer-native.log"
    status_path = raw / "peer-native.status"
    command_path = raw / "peer-native.command.txt"
    host_pid_path = raw / "peer-native.host-pid"
    app_pid_path = raw / "peer-app.pid"
    for path in (log_path, status_path, command_path, host_pid_path, app_pid_path):
        if path.exists():
            raise SystemExit(f"refusing to overwrite {path}")

    command = ["rtk", "proxy", "docker", "exec", container, "/native-peer"]
    command_path.write_text(" ".join(command) + "\n", encoding="utf-8")
    host_pid_path.write_text(f"collector_pid={__import__('os').getpid()}\n", encoding="utf-8")
    start_utc = utc_now()
    start_mono = time.monotonic_ns()
    process = subprocess.Popen(command, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True,
                               encoding="utf-8", errors="replace", bufsize=1)
    with log_path.open("x", encoding="utf-8") as log:
        log.write(f"{TAG} host_utc={start_utc} host_mono_ns={start_mono} "
                  f"event=collector_start host_pid={process.pid} container={container}\n")
        log.flush()
        for line in process.stdout:
            stamp_utc = utc_now()
            stamp_mono = time.monotonic_ns()
            rendered = (f"{TAG} host_utc={stamp_utc} host_mono_ns={stamp_mono} "
                        f"{line.rstrip()}\n")
            log.write(rendered)
            log.flush()
            match = re.search(r"event=process_start pid=(\d+)", line)
            if match and not app_pid_path.exists():
                app_pid_path.write_text(match.group(1) + "\n", encoding="utf-8")
            if "event=peer_ready" in line:
                print(f"{TAG} event=peer_ready host_utc={stamp_utc} "
                      f"host_mono_ns={stamp_mono}", flush=True)
        exit_status = process.wait()
        finish_utc = utc_now()
        finish_mono = time.monotonic_ns()
        log.write(f"{TAG} host_utc={finish_utc} host_mono_ns={finish_mono} "
                  f"event=collector_exit host_exit_status={exit_status}\n")
        log.flush()
    status_path.write_text(
        f"container={container}\nstart_utc={start_utc}\nstart_mono_ns={start_mono}\n"
        f"finish_utc={finish_utc}\nfinish_mono_ns={finish_mono}\n"
        f"host_exit_status={exit_status}\n", encoding="utf-8")
    print(f"{TAG} event=collector_exit host_exit_status={exit_status}", flush=True)
    return exit_status


if __name__ == "__main__":
    raise SystemExit(main())
