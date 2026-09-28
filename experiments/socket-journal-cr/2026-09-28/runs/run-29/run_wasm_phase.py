#!/usr/bin/env python3
"""Launch one iwasm phase and persist timestamped raw output and status."""

import argparse
import datetime
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time


TAG = "[CR-DISCOVERY-PROBE-R29]"
RUN_IN_CONTAINER = "/run"
STATE_IN_CONTAINER = "/state"
IWASM = "/runtime/iwasm"
WASM = "/artifact/echoback_string.wasm"


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


def rtk(*args, **kwargs):
    return subprocess.run(["rtk", *args], check=False, **kwargs)


def remote_process_args(container, pid):
    result = rtk(
        "proxy", "docker", "exec", container, "sh", "-c",
        f"ps -p {pid} -o args=",
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def stop_remote_iwasm(container, pid):
    """Stop only the expected experiment iwasm process and verify its exit."""
    args = remote_process_args(container, pid)
    if args is None:
        return f"pid={pid}:initial-process-check-failed"
    if not args:
        return f"pid={pid}:already-exited"
    if "/runtime/iwasm" not in args or "/artifact/echoback_string.wasm" not in args:
        return f"pid={pid}:identity-mismatch args={args!r}"

    term = rtk(
        "proxy", "docker", "exec", container, "sh", "-c",
        f"kill -TERM {pid}",
        capture_output=True,
        text=True,
    )
    for _ in range(20):
        args = remote_process_args(container, pid)
        if args is None:
            return f"pid={pid}:process-check-failed-after-SIGTERM"
        if not args:
            return f"pid={pid}:SIGTERM-exited term_rc={term.returncode}"
        time.sleep(0.25)

    args = remote_process_args(container, pid)
    if args is None:
        return f"pid={pid}:process-check-failed-before-SIGKILL"
    if "/runtime/iwasm" not in args or "/artifact/echoback_string.wasm" not in args:
        return f"pid={pid}:identity-changed-after-SIGTERM args={args!r}"
    kill = rtk(
        "proxy", "docker", "exec", container, "sh", "-c",
        f"kill -KILL {pid}",
        capture_output=True,
        text=True,
    )
    for _ in range(20):
        args = remote_process_args(container, pid)
        if args is None:
            return f"pid={pid}:process-check-failed-after-SIGKILL"
        if not args:
            return (f"pid={pid}:SIGKILL-exited term_rc={term.returncode} "
                    f"kill_rc={kill.returncode}")
        time.sleep(0.25)
    return f"pid={pid}:still-running-after-SIGKILL args={remote_process_args(container, pid)!r}"


def cleanup_remote_iwasm(container):
    result = rtk(
        "proxy", "docker", "exec", container, "sh", "-c",
        "ps -eo pid=,args=",
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return f"process-scan-failed rc={result.returncode} output={result.stderr!r}"
    pids = []
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) == 2 and fields[0].isdigit():
            if ("/runtime/iwasm" in fields[1]
                    and "/artifact/echoback_string.wasm" in fields[1]):
                pids.append(int(fields[0]))
    if not pids:
        return "no-experiment-iwasm-found"
    return ";".join(stop_remote_iwasm(container, pid) for pid in pids)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("checkpoint", "restore"))
    parser.add_argument("container")
    args = parser.parse_args()

    script_path = Path(__file__).resolve()
    run_dir = script_path.parent
    raw_dir = run_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    log_path = raw_dir / f"wasm-{args.phase}.log"
    status_path = raw_dir / f"wasm-{args.phase}.status"
    container_pid_path = raw_dir / f"wasm-{args.phase}.pid"
    host_pid_path = raw_dir / f"wasm-{args.phase}.host-pid"
    command_path = raw_dir / f"wasm-{args.phase}.command.txt"
    for path in (log_path, status_path, container_pid_path, host_pid_path,
                 command_path):
        if path.exists():
            raise SystemExit(f"refusing to overwrite existing run artifact: {path}")

    container_argv = [IWASM, "--addr-pool=0.0.0.0/0", "--max-threads=32", "-v=5"]
    if args.phase == "restore":
        container_argv.append("--restore")
    container_argv.append(WASM)
    remote_command = (
        f"printf '%s\\n' \"$$\" > {shlex.quote(f'{RUN_IN_CONTAINER}/raw/wasm-{args.phase}.pid')}; "
        f"exec {shlex.join(container_argv)}"
    )
    argv = [
        "rtk", "proxy", "docker", "exec", "--workdir", STATE_IN_CONTAINER,
        args.container, "sh", "-c", remote_command,
    ]
    command_path.write_text(shlex.join(argv) + "\n", encoding="utf-8")
    host_pid_path.write_text(
        f"collector_pid={os.getpid()}\nphase={args.phase}\ncontainer={args.container}\n",
        encoding="utf-8",
    )

    start_utc = utc_now()
    start_mono = time.monotonic_ns()
    print(f"{TAG} host_utc={start_utc} host_mono_ns={start_mono} "
          f"phase={args.phase} collector_pid={os.getpid()} "
          f"event=launch container={args.container}", flush=True)

    process = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    with log_path.open("w", encoding="utf-8") as log_file:
        log_file.write(
            f"{TAG} host_utc={start_utc} host_mono_ns={start_mono} "
            f"phase={args.phase} collector_pid={os.getpid()} "
            f"host_docker_exec_pid={process.pid} event=launch "
            f"container={args.container}\n"
        )
        log_file.flush()
        container_pid = None
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            if container_pid_path.exists():
                contents = container_pid_path.read_text(encoding="utf-8").strip()
                if contents.isdigit():
                    container_pid = int(contents)
                    break
            if process.poll() is not None:
                break
            time.sleep(0.1)

        if container_pid is None:
            cleanup = cleanup_remote_iwasm(args.container)
            process.terminate()
            output, _ = process.communicate(timeout=5)
            log_file.write(
                f"{TAG} host_utc={utc_now()} host_mono_ns={time.monotonic_ns()} "
                f"phase={args.phase} event=pid_acquisition_failed "
                f"remote_cleanup={cleanup!r} output={output!r}\n"
            )
            status_path.write_text(
                f"phase={args.phase}\nresult=pid_acquisition_failed\n"
                f"remote_cleanup={cleanup}\n"
                f"host_exit_status={process.returncode}\n",
                encoding="utf-8",
            )
            return 2

        ps = rtk(
            "proxy", "docker", "exec", args.container, "sh", "-c",
            f"ps -p {container_pid} -o args=",
            capture_output=True,
            text=True,
        )
        command_line = ps.stdout.strip()
        expected_parts = ["iwasm", "echoback_string.wasm"]
        if args.phase == "restore":
            expected_parts.append("--restore")
        else:
            expected_parts.append("--max-threads=32")
        if ps.returncode != 0 or any(part not in command_line for part in expected_parts):
            cleanup = stop_remote_iwasm(args.container, container_pid)
            process.terminate()
            output, _ = process.communicate(timeout=5)
            log_file.write(
                f"{TAG} host_utc={utc_now()} host_mono_ns={time.monotonic_ns()} "
                f"phase={args.phase} container_pid={container_pid} "
                f"event=argv_verification_failed ps_rc={ps.returncode} "
                f"args={command_line!r} remote_cleanup={cleanup!r} "
                f"output={output!r}\n"
            )
            status_path.write_text(
                f"phase={args.phase}\nresult=argv_verification_failed\n"
                f"container_pid={container_pid}\nremote_cleanup={cleanup}\n"
                f"host_exit_status={process.returncode}\n",
                encoding="utf-8",
            )
            return 2

        log_file.write(
            f"{TAG} host_utc={utc_now()} host_mono_ns={time.monotonic_ns()} "
            f"phase={args.phase} container_pid={container_pid} "
            f"event=process_verified args={command_line!r}\n"
        )
        log_file.flush()
        print(f"{TAG} phase={args.phase} container_pid={container_pid} "
              f"event=process_verified args={command_line}", flush=True)

        for line in process.stdout:
            prefix = (
                f"{TAG} host_utc={utc_now()} host_mono_ns={time.monotonic_ns()} "
                f"phase={args.phase} container_pid={container_pid} "
            )
            rendered = prefix + line.rstrip("\n") + "\n"
            log_file.write(rendered)
            log_file.flush()
            sys.stdout.write(rendered)
            sys.stdout.flush()

        exit_status = process.wait()
        finish_utc = utc_now()
        finish_mono = time.monotonic_ns()
        status = (
            f"phase={args.phase}\n"
            f"container={args.container}\n"
            f"container_pid={container_pid}\n"
            f"collector_pid={os.getpid()}\n"
            f"host_docker_exec_pid={process.pid}\n"
            f"start_utc={start_utc}\n"
            f"start_mono_ns={start_mono}\n"
            f"finish_utc={finish_utc}\n"
            f"finish_mono_ns={finish_mono}\n"
            f"host_exit_status={exit_status}\n"
        )
        status_path.write_text(status, encoding="utf-8")
        log_file.write(
            f"{TAG} host_utc={finish_utc} host_mono_ns={finish_mono} "
            f"phase={args.phase} container_pid={container_pid} "
            f"event=process_exit exit_status={exit_status}\n"
        )
        log_file.flush()
    print(f"{TAG} phase={args.phase} container_pid={container_pid} "
          f"event=process_exit exit_status={exit_status}", flush=True)
    return exit_status


if __name__ == "__main__":
    raise SystemExit(main())
