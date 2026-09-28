#!/usr/bin/env python3
"""Send SIGUSR2 only after the native-peer and no-C/R gates pass."""

from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
import time


TAG = "[CR-RERUN-20260927-R04]"
CONTAINER = "mros2-cr-run04-wamr"
RUN_DIR = Path(__file__).resolve().parent
RAW = RUN_DIR / "raw"
PUBLISH_RE = re.compile(r"APP publish_begin topic=/to_linux id=(\d+)")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def status_passed(path):
    if not path.is_file():
        return False
    return re.search(r"^result=(?:pass|gate_pass)$", path.read_text(), re.MULTILINE) is not None


def main():
    log_path = RAW / "checkpoint-signal.log"
    if log_path.exists():
        raise SystemExit(f"refusing to overwrite {log_path}")
    if not (RAW / "gate-pass.ok").is_file():
        raise SystemExit("pre-C/R gate marker is absent")
    if not status_passed(RAW / "no-cr-baseline.status"):
        raise SystemExit("30-second no-C/R baseline did not pass")

    wasm_log = RAW / "wasm-checkpoint.log"
    publish_ids = [int(value) for value in PUBLISH_RE.findall(
        wasm_log.read_text(encoding="utf-8", errors="replace"))]
    if not publish_ids:
        raise SystemExit("no Wasm publish IDs found")
    pid_path = RAW / "wasm-checkpoint.pid"
    if not pid_path.is_file():
        raise SystemExit("checkpoint iwasm PID file is absent")
    pid_text = pid_path.read_text(encoding="utf-8").strip()
    if not pid_text.isdigit():
        raise SystemExit(f"invalid checkpoint iwasm PID: {pid_text!r}")
    pid = int(pid_text)

    check = subprocess.run(
        ["rtk", "proxy", "docker", "exec", CONTAINER,
         "sh", "-c", f"ps -p {pid} -o args="],
        check=False, capture_output=True, text=True)
    args = check.stdout.strip()
    required = ("/runtime/iwasm", "--addr-pool=0.0.0.0/0",
                "--max-threads=32", "/artifact/echoback_string.wasm")
    if check.returncode != 0 or not all(part in args for part in required):
        raise SystemExit(f"checkpoint process identity check failed: rc={check.returncode} args={args!r}")
    if "--restore" in args:
        raise SystemExit("refusing to signal a restore-phase process")

    command = ["rtk", "docker", "exec", CONTAINER, "kill", "-USR2", str(pid)]
    before_utc = utc_now()
    before_ns = time.monotonic_ns()
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    after_utc = utc_now()
    after_ns = time.monotonic_ns()
    record = (
        f"{TAG} event=checkpoint_signal container={CONTAINER} pid={pid} "
        f"checkpoint_max_publish_id={max(publish_ids)} "
        f"pre_signal_publish_count={len(publish_ids)} "
        f"before_utc={before_utc} before_mono_ns={before_ns} "
        f"after_utc={after_utc} after_mono_ns={after_ns} "
        f"command={' '.join(command)} returncode={result.returncode} "
        f"stdout={result.stdout.strip()!r} stderr={result.stderr.strip()!r} "
        f"process_args={args!r}\n"
    )
    with log_path.open("x", encoding="utf-8") as log:
        log.write(record)
    print(record, end="", flush=True)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
