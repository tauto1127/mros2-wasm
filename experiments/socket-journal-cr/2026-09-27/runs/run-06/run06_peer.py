#!/usr/bin/env python3
"""Launch and timestamp stdout from the run-04 native mROS 2 peer binary."""

import shlex
import subprocess
import sys
import time

from run06_common import CONTAINERS, RAW, rtk, utc_now, mono_ns, write_new


def main():
    if len(sys.argv) != 1:
        raise SystemExit("usage: run06_peer.py")
    container = CONTAINERS["peer"]
    pid_path = RAW / "peer-native.pid"
    log_path = RAW / "peer-native.log"
    status_path = RAW / "peer-native.status"
    command_path = RAW / "peer-native.command.txt"
    for path in (pid_path, log_path, status_path, command_path):
        if path.exists():
            raise SystemExit(f"refusing to overwrite existing run artifact: {path}")

    remote_command = 'echo $$ > /run/raw/peer-native.pid; exec /native-peer'
    argv = ["rtk", "proxy", "docker", "exec", container, "sh", "-c", remote_command]
    write_new(command_path, shlex.join(argv) + "\n")
    start_utc = utc_now()
    start_ns = mono_ns()
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace", bufsize=1)
    with log_path.open("x", encoding="utf-8") as log:
        log.write(f"[CR-RUN06-PEER] host_utc={start_utc} host_mono_ns={start_ns} "
                  f"event=collector_start host_pid={process.pid} container={container}\n")
        log.flush()
        deadline = time.monotonic() + 15
        peer_pid = None
        while time.monotonic() < deadline:
            if pid_path.exists():
                value = pid_path.read_text(encoding="utf-8").strip()
                if value.isdigit():
                    peer_pid = int(value)
                    break
            if process.poll() is not None:
                break
            time.sleep(0.1)

        if peer_pid is None:
            process.terminate()
            output, _ = process.communicate(timeout=5)
            log.write(f"[CR-RUN06-PEER] host_utc={utc_now()} host_mono_ns={mono_ns()} "
                      f"event=pid_acquisition_failed output={output!r}\n")
            write_new(status_path, f"result=pid_acquisition_failed\nhost_exit_status={process.returncode}\n")
            return 2

        check = rtk(["docker", "exec", container, "sh", "-c", f"ps -p {peer_pid} -o args="], timeout=10)
        args = check.stdout.strip()
        if check.returncode or "/native-peer" not in args:
            process.terminate()
            output, _ = process.communicate(timeout=5)
            log.write(f"[CR-RUN06-PEER] host_utc={utc_now()} host_mono_ns={mono_ns()} "
                      f"event=process_identity_failed pid={peer_pid} args={args!r} "
                      f"rc={check.returncode} output={output!r}\n")
            write_new(status_path, f"result=process_identity_failed\ncontainer_pid={peer_pid}\nargs={args!r}\n")
            return 2

        log.write(f"[CR-RUN06-PEER] host_utc={utc_now()} host_mono_ns={mono_ns()} "
                  f"event=process_verified container_pid={peer_pid} args={args!r}\n")
        log.flush()
        print(f"[CR-RUN06-PEER] event=process_verified container_pid={peer_pid} args={args}", flush=True)
        for line in process.stdout:
            rendered = (f"[CR-RUN06-PEER] host_utc={utc_now()} host_mono_ns={mono_ns()} "
                        f"container_pid={peer_pid} " + line.rstrip("\n") + "\n")
            log.write(rendered)
            log.flush()
            sys.stdout.write(rendered)
            sys.stdout.flush()
        exit_status = process.wait()
        finish = f"result=process_exit\ncontainer={container}\ncontainer_pid={peer_pid}\nhost_exit_status={exit_status}\n"
        write_new(status_path, finish)
        log.write(f"[CR-RUN06-PEER] host_utc={utc_now()} host_mono_ns={mono_ns()} "
                  f"event=process_exit exit_status={exit_status}\n")
        log.flush()
    return exit_status


if __name__ == "__main__":
    raise SystemExit(main())
