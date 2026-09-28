#!/usr/bin/env python3
"""Enforce the 60-second gate deadline for one verified iwasm process."""

import datetime
from pathlib import Path
import re
import subprocess
import sys
import time


TAG = "[CR-RERUN-20260927-R04]"
GATE_NS = 60_000_000_000
VERIFY_WAIT_NS = 30_000_000_000


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


def rtk(*args):
    return subprocess.run(["rtk", *args], check=False, capture_output=True, text=True)


def process_verified_mono_ns(path):
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8", errors="replace") as log:
        for line in log:
            if "event=process_verified" not in line:
                continue
            match = re.search(r"\bhost_mono_ns=(\d+)\b", line)
            return int(match.group(1)) if match else None
    return None


def gate_marker_mono_ns(path):
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"^gate_pass_host_mono_ns=(\d+)\s*$", content, re.MULTILINE)
    return int(match.group(1)) if match else None


def process_state(container, pid):
    result = rtk("proxy", "docker", "exec", container, "sh", "-c",
                 f"ps -p {pid} -o args=")
    if result.returncode != 0:
        return "error", "", result.stderr.strip() or result.stdout.strip()
    args = result.stdout.strip()
    return ("absent" if not args else "present"), args, ""


def is_expected_checkpoint_iwasm(args):
    required = ("/runtime/iwasm", "--addr-pool=0.0.0.0/0", "--max-threads=32",
                "-v=5", "/artifact/echoback_string.wasm")
    return all(part in args for part in required) and "--restore" not in args


def stop_runner(container):
    return rtk("docker", "stop", "--time", "2", container)


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: gate_watchdog.py CONTAINER")
    container = sys.argv[1]
    raw = Path(__file__).resolve().parent / "raw"
    phase_log = raw / "wasm-checkpoint.log"
    pid_path = raw / "wasm-checkpoint.pid"
    pass_path = raw / "gate-pass.ok"
    collector_status = raw / "wasm-checkpoint.status"
    watchdog_log = raw / "gate-watchdog.log"
    status_path = raw / "gate-watchdog.status"
    for path in (watchdog_log, status_path):
        if path.exists():
            raise SystemExit(f"refusing to overwrite existing artifact: {path}")
    script_start_ns = time.monotonic_ns()
    with watchdog_log.open("x", encoding="utf-8") as log:
        def record(event, **fields):
            details = " ".join(f"{key}={value!r}" for key, value in fields.items())
            line = f"{TAG} utc={utc_now()} host_mono_ns={time.monotonic_ns()} event={event} {details}\n"
            log.write(line)
            log.flush()
            print(line, end="", flush=True)

        def finish(result, **fields):
            status_path.write_text(
                f"result={result}\n" + "".join(f"{key}={value}\n" for key, value in fields.items()),
                encoding="utf-8",
            )

        record("watchdog_start", container=container, gate_seconds=60,
               pass_marker=str(pass_path))
        if pass_path.exists():
            record("preexisting_gate_marker_rejected", marker=str(pass_path))
            finish("preexisting_gate_marker_rejected")
            return 2

        verified_ns = None
        while verified_ns is None:
            if pass_path.exists():
                record("preverification_gate_marker_rejected", marker=str(pass_path))
                finish("preverification_gate_marker_rejected")
                return 2
            verified_ns = process_verified_mono_ns(phase_log)
            if verified_ns is not None:
                record("process_verified_seen", process_verified_mono_ns=verified_ns,
                       deadline_mono_ns=verified_ns + GATE_NS)
                break
            if collector_status.exists():
                record("collector_exited_before_process_verified")
                finish("collector_exited_before_process_verified")
                return 2
            if time.monotonic_ns() - script_start_ns >= VERIFY_WAIT_NS:
                record("process_verified_not_seen_timeout")
                finish("process_verified_not_seen_timeout")
                return 2
            time.sleep(0.05)

        deadline_ns = verified_ns + GATE_NS
        invalid_marker_reported = False
        while time.monotonic_ns() < deadline_ns:
            marker_ns = gate_marker_mono_ns(pass_path)
            if marker_ns is not None:
                if verified_ns <= marker_ns <= deadline_ns and marker_ns <= time.monotonic_ns():
                    record("gate_pass_marker_accepted", marker_mono_ns=marker_ns)
                    finish("gate_pass", marker_mono_ns=marker_ns)
                    return 0
                if not invalid_marker_reported:
                    record("invalid_gate_pass_marker_ignored", marker_mono_ns=marker_ns,
                           process_verified_mono_ns=verified_ns, deadline_mono_ns=deadline_ns)
                    invalid_marker_reported = True
            elif pass_path.exists() and not invalid_marker_reported:
                record("malformed_gate_pass_marker_ignored", marker=str(pass_path))
                invalid_marker_reported = True
            if collector_status.exists():
                record("collector_exited_before_gate_decision")
                finish("collector_exited_before_gate_decision")
                return 2
            time.sleep(0.05)

        marker_ns = gate_marker_mono_ns(pass_path)
        if (marker_ns is not None and verified_ns <= marker_ns <= deadline_ns
                and marker_ns <= time.monotonic_ns()):
            record("gate_pass_marker_accepted_at_deadline", marker_mono_ns=marker_ns)
            finish("gate_pass", marker_mono_ns=marker_ns)
            return 0

        if not pid_path.exists():
            record("gate_timeout_pid_file_missing", pid_file=str(pid_path))
            runner_stop = stop_runner(container)
            record("fallback_runner_stop", returncode=runner_stop.returncode,
                   output=runner_stop.stdout.strip(), error=runner_stop.stderr.strip())
            finish("gate_timeout_pid_file_missing_runner_stop", runner_stop_rc=runner_stop.returncode)
            return 0 if runner_stop.returncode == 0 else 2
        pid_text = pid_path.read_text(encoding="utf-8").strip()
        if not pid_text.isdigit():
            record("gate_timeout_pid_invalid", pid_value=pid_text)
            runner_stop = stop_runner(container)
            record("fallback_runner_stop", returncode=runner_stop.returncode,
                   output=runner_stop.stdout.strip(), error=runner_stop.stderr.strip())
            finish("gate_timeout_pid_invalid_runner_stop", runner_stop_rc=runner_stop.returncode)
            return 0 if runner_stop.returncode == 0 else 2

        pid = int(pid_text)
        state, args, error = process_state(container, pid)
        if state == "absent":
            record("gate_timeout_process_already_absent", pid=pid)
            finish("gate_timeout_process_already_absent", pid=pid)
            return 0
        if state == "error":
            record("gate_timeout_process_check_error", pid=pid, error=error)
            runner_stop = stop_runner(container)
            record("fallback_runner_stop", returncode=runner_stop.returncode,
                   output=runner_stop.stdout.strip(), error=runner_stop.stderr.strip())
            finish("gate_timeout_check_error_runner_stop", pid=pid,
                   runner_stop_rc=runner_stop.returncode)
            return 0 if runner_stop.returncode == 0 else 2
        if not is_expected_checkpoint_iwasm(args):
            record("gate_timeout_process_identity_mismatch", pid=pid, args=args)
            runner_stop = stop_runner(container)
            record("fallback_runner_stop", returncode=runner_stop.returncode,
                   output=runner_stop.stdout.strip(), error=runner_stop.stderr.strip())
            finish("gate_timeout_identity_mismatch_runner_stop", pid=pid,
                   runner_stop_rc=runner_stop.returncode)
            return 0 if runner_stop.returncode == 0 else 2

        term = rtk("proxy", "docker", "exec", container, "sh", "-c", f"kill -TERM {pid}")
        record("gate_timeout_sigterm_sent", pid=pid, returncode=term.returncode,
               args=args, error=term.stderr.strip())
        for _ in range(40):
            state, args, error = process_state(container, pid)
            if state == "absent":
                record("gate_timeout_sigterm_confirmed", pid=pid)
                finish("gate_timeout_sigterm", pid=pid)
                return 0
            if state == "error" or not is_expected_checkpoint_iwasm(args):
                record("gate_timeout_after_term_unverifiable", pid=pid, args=args, error=error)
                runner_stop = stop_runner(container)
                record("fallback_runner_stop", returncode=runner_stop.returncode,
                       output=runner_stop.stdout.strip(), error=runner_stop.stderr.strip())
                finish("gate_timeout_after_term_runner_stop", pid=pid,
                       runner_stop_rc=runner_stop.returncode)
                return 0 if runner_stop.returncode == 0 else 2
            time.sleep(0.1)

        state, args, error = process_state(container, pid)
        if state == "present" and is_expected_checkpoint_iwasm(args):
            kill = rtk("proxy", "docker", "exec", container, "sh", "-c", f"kill -KILL {pid}")
            record("gate_timeout_identity_checked_sigkill_sent", pid=pid,
                   returncode=kill.returncode, error=kill.stderr.strip())
            for _ in range(40):
                state, args, error = process_state(container, pid)
                if state == "absent":
                    record("gate_timeout_sigkill_confirmed", pid=pid)
                    finish("gate_timeout_sigkill", pid=pid)
                    return 0
                if state == "error" or not is_expected_checkpoint_iwasm(args):
                    break
                time.sleep(0.1)

        record("gate_timeout_runner_stop_fallback", pid=pid, process_state=state,
               args=args, error=error)
        runner_stop = stop_runner(container)
        record("fallback_runner_stop", returncode=runner_stop.returncode,
               output=runner_stop.stdout.strip(), error=runner_stop.stderr.strip())
        finish("gate_timeout_runner_stop_fallback", pid=pid,
               runner_stop_rc=runner_stop.returncode)
        return 0 if runner_stop.returncode == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
