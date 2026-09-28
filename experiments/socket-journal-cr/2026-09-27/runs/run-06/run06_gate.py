#!/usr/bin/env python3
"""ID-correlated end-to-end gates for the run-06 Docker IP migration test."""

from datetime import datetime, timezone
import re
import sys
import time

from run06_common import RAW, mono_ns, utc_now, write_new


PUBLISH = re.compile(r"APP publish_begin topic=/to_linux id=(\d+)")
RECEIVE = re.compile(r"event=peer_receive topic=/to_linux id=(\d+)")
ECHO = re.compile(r"event=peer_echo_publish_return topic=/to_stm id=(\d+)")
CALLBACK = re.compile(r"APP callback topic=/to_stm id=(\d+)")


def read(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def ids(pattern, content):
    return {int(item) for item in pattern.findall(content)}


def record(stream, event, **fields):
    details = " ".join(f"{key}={value!r}" for key, value in fields.items())
    line = f"[CR-RUN06-GATE] utc={utc_now()} mono_ns={mono_ns()} event={event} {details}\n"
    stream.write(line)
    stream.flush()
    print(line, end="", flush=True)


def verified_at(path):
    for line in read(path).splitlines():
        if "event=process_verified" in line:
            match = re.search(r"\bhost_mono_ns=(\d+)\b", line)
            if match:
                return int(match.group(1))
    return None


def wait_verified(log_path, status_path, timeout_seconds=30):
    started = time.monotonic()
    while time.monotonic() - started < timeout_seconds:
        value = verified_at(log_path)
        if value is not None:
            return value
        if status_path.exists():
            raise RuntimeError(f"WAMR collector exited before process verification: {status_path}")
        time.sleep(0.05)
    raise TimeoutError(f"process_verified not seen within {timeout_seconds}s: {log_path}")


def counts(wasm, peer, floor=None):
    published = ids(PUBLISH, wasm)
    received = ids(RECEIVE, peer)
    echoed = ids(ECHO, peer)
    callbacks = ids(CALLBACK, wasm)
    full = published & received & echoed & callbacks
    if floor is not None:
        full = {item for item in full if item > floor}
    return {
        "published": published,
        "received": received,
        "echoed": echoed,
        "callbacks": callbacks,
        "full": full,
        "peer_ready": "event=peer_ready" in peer,
    }


def pre_gate():
    wasm_log = RAW / "wasm-checkpoint.log"
    peer_log = RAW / "peer-native.log"
    phase_status = RAW / "wasm-checkpoint.status"
    log_path = RAW / "roundtrip-gate.log"
    status_path = RAW / "roundtrip-gate.status"
    marker = RAW / "gate-pass.ok"
    for path in (log_path, status_path, marker):
        if path.exists():
            raise SystemExit(f"refusing to overwrite {path}")
    with log_path.open("x", encoding="utf-8") as stream:
        start = time.monotonic_ns()
        record(stream, "gate_start", deadline_seconds=60, required_full_roundtrips=10)
        try:
            verified = wait_verified(wasm_log, phase_status)
        except Exception as error:
            record(stream, "process_verification_failed", error=str(error))
            write_new(status_path, f"result=process_verification_failed\nerror={error}\n")
            return 2
        deadline = verified + 60_000_000_000
        while time.monotonic_ns() < deadline:
            result = counts(read(wasm_log), read(peer_log))
            if result["peer_ready"] and len(result["full"]) >= 10:
                marker_ns = mono_ns()
                selected = sorted(result["full"])
                write_new(marker, f"gate_pass_host_mono_ns={marker_ns}\n"
                          f"distinct_roundtrip_ids={','.join(map(str, selected))}\n")
                record(stream, "gate_pass", process_verified_mono_ns=verified,
                       full_roundtrip_ids=selected, published=len(result["published"]),
                       peer_received=len(result["received"]), peer_echoed=len(result["echoed"]),
                       wasm_callbacks=len(result["callbacks"]), peer_ready=True)
                write_new(status_path, f"result=pass\nprocess_verified_mono_ns={verified}\n"
                          f"roundtrip_ids={','.join(map(str, selected))}\n"
                          f"count={len(selected)}\n")
                return 0
            time.sleep(0.1)
        result = counts(read(wasm_log), read(peer_log))
        record(stream, "gate_timeout", elapsed_ns=mono_ns() - start,
               full_roundtrip_ids=sorted(result["full"]), peer_ready=result["peer_ready"],
               published=len(result["published"]), peer_received=len(result["received"]),
               peer_echoed=len(result["echoed"]), wasm_callbacks=len(result["callbacks"]))
        write_new(status_path, f"result=timeout\nfull_roundtrip_count={len(result['full'])}\n"
                  f"peer_ready={str(result['peer_ready']).lower()}\n")
        return 1


def baseline():
    marker = RAW / "gate-pass.ok"
    wasm_path = RAW / "wasm-checkpoint.log"
    peer_path = RAW / "peer-native.log"
    log_path = RAW / "no-cr-baseline.log"
    status_path = RAW / "no-cr-baseline.status"
    if not marker.is_file():
        raise SystemExit("pre-C/R gate marker is absent; refusing baseline")
    if log_path.exists() or status_path.exists():
        raise SystemExit("refusing to overwrite no-C/R baseline artifacts")
    wasm = read(wasm_path)
    initial = ids(PUBLISH, wasm)
    if not initial:
        raise SystemExit("no Wasm publishes recorded at baseline start")
    start_max = max(initial)
    start_ns = mono_ns()
    start_utc = utc_now()
    with log_path.open("x", encoding="utf-8") as stream:
        record(stream, "baseline_start", start_max_publish_id=start_max, duration_seconds=30)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            time.sleep(0.2)
        result = counts(read(wasm_path), read(peer_path), floor=start_max)
        selected = sorted(result["full"])
        verdict = "pass" if result["peer_ready"] and len(selected) >= 10 else "fail"
        finish_ns = mono_ns()
        record(stream, "baseline_result", result=verdict, start_utc=start_utc,
               start_mono_ns=start_ns, finish_mono_ns=finish_ns,
               duration_ns=finish_ns - start_ns, start_max_publish_id=start_max,
               full_roundtrip_ids=selected, full_roundtrip_count=len(selected),
               peer_ready=result["peer_ready"])
        write_new(status_path, f"result={verdict}\nstart_utc={start_utc}\n"
                  f"start_max_publish_id={start_max}\nfinish_max_publish_id="
                  f"{max(ids(PUBLISH, read(wasm_path)))}\n"
                  f"new_roundtrip_ids={','.join(map(str, selected))}\n"
                  f"new_roundtrip_count={len(selected)}\npeer_ready={str(result['peer_ready']).lower()}\n")
    return 0 if verdict == "pass" else 1


def post_gate(checkpoint_max):
    wasm_log = RAW / "wasm-restore.log"
    peer_log = RAW / "peer-native.log"
    phase_status = RAW / "wasm-restore.status"
    log_path = RAW / "postcr-gate.log"
    status_path = RAW / "postcr-gate.status"
    if log_path.exists() or status_path.exists():
        raise SystemExit("refusing to overwrite post-C/R gate artifacts")
    with log_path.open("x", encoding="utf-8") as stream:
        record(stream, "postcr_gate_start", checkpoint_max=checkpoint_max, deadline_seconds=90)
        try:
            verified = wait_verified(wasm_log, phase_status)
        except Exception as error:
            record(stream, "restore_process_verification_failed", error=str(error))
            write_new(status_path, f"result=process_verification_failed\ncheckpoint_max={checkpoint_max}\nerror={error}\n")
            return 2
        deadline = verified + 90_000_000_000
        while time.monotonic_ns() < deadline:
            result = counts(read(wasm_log), read(peer_log), floor=checkpoint_max)
            if result["peer_ready"] and len(result["full"]) >= 10:
                selected = sorted(result["full"])
                record(stream, "postcr_gate_pass", checkpoint_max=checkpoint_max,
                       process_verified_mono_ns=verified, full_roundtrip_ids=selected)
                write_new(status_path, f"result=pass\ncheckpoint_max={checkpoint_max}\n"
                          f"roundtrip_ids={','.join(map(str, selected))}\ncount={len(selected)}\n")
                return 0
            time.sleep(0.1)
        result = counts(read(wasm_log), read(peer_log), floor=checkpoint_max)
        published_after = {item for item in result["published"] if item > checkpoint_max}
        received_after = {item for item in result["received"] if item > checkpoint_max}
        echoed_after = {item for item in result["echoed"] if item > checkpoint_max}
        callbacks_after = {item for item in result["callbacks"] if item > checkpoint_max}
        record(stream, "postcr_gate_timeout", checkpoint_max=checkpoint_max,
               full_roundtrip_ids=sorted(result["full"]), peer_ready=result["peer_ready"],
               published_count=len(published_after), peer_received_count=len(received_after),
               peer_echo_count=len(echoed_after), wasm_callback_count=len(callbacks_after))
        write_new(status_path, f"result=timeout\ncheckpoint_max={checkpoint_max}\n"
                  f"full_roundtrip_ids={','.join(map(str, sorted(result['full'])))}\n"
                  f"full_roundtrip_count={len(result['full'])}\n"
                  f"peer_ready={str(result['peer_ready']).lower()}\n")
        return 1


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "pre":
        return pre_gate()
    if len(sys.argv) == 2 and sys.argv[1] == "baseline":
        return baseline()
    if len(sys.argv) == 3 and sys.argv[1] == "post" and sys.argv[2].isdigit():
        return post_gate(int(sys.argv[2]))
    raise SystemExit("usage: run06_gate.py {pre|baseline|post CHECKPOINT_MAX_PUBLISH_ID}")


if __name__ == "__main__":
    raise SystemExit(main())
