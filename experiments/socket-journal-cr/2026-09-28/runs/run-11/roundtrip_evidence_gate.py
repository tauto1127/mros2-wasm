#!/usr/bin/env python3
"""Application-level round-trip gates for run-11.

The acceptance rule is fixed in procedure.md. A round trip needs the same ID
and body on all four application log lines, intra-log order, an increasing
native epoch, a Wasm callback after the native echo return, and publish/receive
host times that agree or differ by less than COLLECTOR_SKEW_MAX_NS.
"""

from datetime import datetime, timezone
from pathlib import Path
import json
import re
import sys
import time


TAG = "[CR-DISCOVERY-PROBE-R11]"
RAW = Path(__file__).resolve().parent / "raw"
PRE_WINDOW_NS = 60_000_000_000
BASELINE_WINDOW_NS = 30_000_000_000
POST_WINDOW_NS = 90_000_000_000
VERIFY_WAIT_NS = 30_000_000_000
COLLECTOR_SKEW_MAX_NS = 100_000_000
HOST_MONO_RE = re.compile(r"\bhost_mono_ns=(\d+)\b")
EPOCH_RE = re.compile(r"\bepoch=([0-9]+(?:\.[0-9]+)?)\b")
PUBLISH_RE = re.compile(r"APP publish_begin topic=/to_linux id=(\d+) payload='([^']*)'")
RECEIVE_RE = re.compile(r"event=peer_receive topic=/to_linux id=(\d+) payload='([^']*)'")
ECHO_RE = re.compile(r"event=peer_echo_publish_return topic=/to_stm id=(\d+) payload='([^']*)'")
CALLBACK_RE = re.compile(r"APP callback topic=/to_stm id=(\d+) payload='([^']*)'")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def read(path):
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def process_verified_ns(path):
    for line in read(path).splitlines():
        if "event=process_verified" in line:
            match = HOST_MONO_RE.search(line)
            if match:
                return int(match.group(1))
    return None


def parse_events(content, pattern, kind):
    events = []
    for line_number, line in enumerate(content.splitlines(), 1):
        match = pattern.search(line)
        stamp = HOST_MONO_RE.search(line)
        if not match or not stamp:
            continue
        epoch_match = EPOCH_RE.search(line)
        events.append({
            "kind": kind,
            "id": int(match.group(1)),
            "payload": match.group(2),
            "mono_ns": int(stamp.group(1)),
            "line": line_number,
            "epoch": float(epoch_match.group(1)) if epoch_match else None,
        })
    return events


def classify_order(publish, receive, echo, callback):
    intra = publish["line"] < callback["line"] and receive["line"] < echo["line"]
    epoch_ok = (
        receive["epoch"] is not None and echo["epoch"] is not None
        and echo["epoch"] > receive["epoch"]
    )
    callback_after_echo = callback["mono_ns"] > echo["mono_ns"]
    echo_after_receive = echo["mono_ns"] >= receive["mono_ns"]
    skew_ns = publish["mono_ns"] - receive["mono_ns"]
    if receive["mono_ns"] >= publish["mono_ns"] and echo_after_receive and callback_after_echo:
        skew_class = "host_mono"
        publish_before_receive = True
    elif 0 < skew_ns < COLLECTOR_SKEW_MAX_NS and echo_after_receive and callback_after_echo:
        skew_class = "collector_skew"
        publish_before_receive = True
    else:
        skew_class = "unordered"
        publish_before_receive = False
    accepted = intra and epoch_ok and publish_before_receive
    return accepted, skew_class, skew_ns


def full_roundtrips(wasm_text, peer_text, lower_ns, upper_ns, min_id=None):
    publishes = parse_events(wasm_text, PUBLISH_RE, "publish")
    receives = parse_events(peer_text, RECEIVE_RE, "receive")
    echoes = parse_events(peer_text, ECHO_RE, "echo")
    callbacks = parse_events(wasm_text, CALLBACK_RE, "callback")

    def in_window(event):
        return lower_ns <= event["mono_ns"] <= upper_ns

    publishes = [event for event in publishes if in_window(event)]
    receives = [event for event in receives if in_window(event)]
    echoes = [event for event in echoes if in_window(event)]
    callbacks = [event for event in callbacks if in_window(event)]

    by_id = {}
    for publish in sorted(publishes, key=lambda event: (event["mono_ns"], event["line"])):
        message_id = publish["id"]
        if min_id is not None and message_id <= min_id:
            continue
        if message_id in by_id:
            continue
        payload = publish["payload"]
        receive = next((event for event in receives
                        if event["id"] == message_id and event["payload"] == payload), None)
        echo = next((event for event in echoes
                     if receive and event["id"] == message_id and event["payload"] == payload
                     and event["line"] > receive["line"]), None)
        callback = next((event for event in callbacks
                         if event["id"] == message_id and event["payload"] == payload
                         and event["line"] > publish["line"]), None)
        if receive is None:
            last_stage = "wasm_publish"
        elif echo is None:
            last_stage = "native_receive"
        elif callback is None:
            last_stage = "native_echo_publish_return"
        else:
            last_stage = "wasm_callback"
        item = {
            "id": message_id,
            "payload": payload,
            "last_stage": last_stage,
            "publish_line": publish["line"],
            "publish_mono_ns": publish["mono_ns"],
        }
        if receive:
            item["receive_line"] = receive["line"]
            item["receive_mono_ns"] = receive["mono_ns"]
            item["receive_epoch"] = receive["epoch"]
        if echo:
            item["echo_line"] = echo["line"]
            item["echo_mono_ns"] = echo["mono_ns"]
            item["echo_epoch"] = echo["epoch"]
        if callback:
            item["callback_line"] = callback["line"]
            item["callback_mono_ns"] = callback["mono_ns"]
        if receive and echo and callback:
            accepted, skew_class, skew_ns = classify_order(publish, receive, echo, callback)
            item["order"] = skew_class
            item["publish_minus_receive_ns"] = skew_ns
            item["accepted"] = accepted
        else:
            item["accepted"] = False
            item["order"] = "incomplete"
        by_id[message_id] = item

    complete = [item for item in by_id.values() if item["accepted"]]
    incomplete = [item for item in by_id.values() if not item["accepted"]]
    complete.sort(key=lambda item: (item["publish_mono_ns"], item["id"]))
    incomplete.sort(key=lambda item: (item["publish_mono_ns"], item["id"]))
    strict = [item for item in complete if item["order"] == "host_mono"]
    return {
        "complete": complete,
        "incomplete": incomplete,
        "strict": strict,
        "publish_events": len(publishes),
        "native_receive_events": len(receives),
        "native_echo_return_events": len(echoes),
        "wasm_callback_events": len(callbacks),
    }


def write_gate(name, result, start_utc, start_ns, finish_utc, finish_ns,
               evaluated, **extra):
    log_path = RAW / f"{name}.log"
    status_path = RAW / f"{name}.status"
    for path in (log_path, status_path):
        if path.exists():
            raise SystemExit(f"refusing to overwrite {path}")
    complete = evaluated["complete"]
    fields = {
        "result": result,
        "start_utc": start_utc,
        "start_mono_ns": start_ns,
        "finish_utc": finish_utc,
        "finish_mono_ns": finish_ns,
        "duration_ns": finish_ns - start_ns,
        "publish_events": evaluated["publish_events"],
        "native_receive_events": evaluated["native_receive_events"],
        "native_echo_return_events": evaluated["native_echo_return_events"],
        "wasm_callback_events": evaluated["wasm_callback_events"],
        "complete_roundtrips": len(complete),
        "strict_host_mono_roundtrips": len(evaluated["strict"]),
        "collector_skew_roundtrips": sum(item["order"] == "collector_skew" for item in complete),
        "incomplete_publishes": len(evaluated["incomplete"]),
        **extra,
    }
    with log_path.open("x", encoding="utf-8") as log:
        log.write(f"{TAG} event=gate_result name={name} "
                  f"{json.dumps(fields, ensure_ascii=False, sort_keys=True)}\n")
        for item in complete:
            log.write(f"{TAG} event=complete_roundtrip "
                      f"{json.dumps(item, ensure_ascii=False, sort_keys=True)}\n")
        for item in evaluated["incomplete"]:
            log.write(f"{TAG} event=incomplete_publish "
                      f"{json.dumps(item, ensure_ascii=False, sort_keys=True)}\n")
    status_path.write_text(
        "".join(f"{key}={value}\n" for key, value in fields.items())
        + "complete_ids=" + ",".join(str(item["id"]) for item in complete) + "\n"
        + "strict_ids=" + ",".join(str(item["id"]) for item in evaluated["strict"]) + "\n",
        encoding="utf-8")
    print(f"{TAG} event=gate_result name={name} result={result} "
          f"complete_count={len(complete)} strict_count={len(evaluated['strict'])} "
          f"ids={','.join(str(item['id']) for item in complete)}", flush=True)


def empty_eval():
    return {
        "complete": [], "incomplete": [], "strict": [],
        "publish_events": 0, "native_receive_events": 0,
        "native_echo_return_events": 0, "wasm_callback_events": 0,
    }


def evaluate(wasm_path, peer_path, lower_ns, upper_ns, min_id=None):
    evaluated = full_roundtrips(read(wasm_path), read(peer_path), lower_ns, upper_ns, min_id)
    evaluated["peer_ready"] = "event=peer_ready" in read(peer_path)
    return evaluated


def wait_for_verified(path, status_path, started_ns, wait_limit_ns):
    while True:
        verified_ns = process_verified_ns(path)
        if verified_ns is not None:
            return verified_ns
        if status_path.exists():
            return None
        if time.monotonic_ns() - started_ns >= wait_limit_ns:
            return None
        time.sleep(0.05)


def passed(evaluated):
    return evaluated.get("peer_ready") and len(evaluated["complete"]) >= 10


def run_pre():
    name = "roundtrip-gate"
    wasm_path, peer_path = RAW / "wasm-checkpoint.log", RAW / "peer-native.log"
    start_utc, start_ns = utc_now(), time.monotonic_ns()
    verified_ns = wait_for_verified(wasm_path, RAW / "wasm-checkpoint.status",
                                    start_ns, VERIFY_WAIT_NS)
    if verified_ns is None:
        write_gate(name, "process_verification_failed", start_utc, start_ns,
                   utc_now(), time.monotonic_ns(), empty_eval(),
                   detail="checkpoint iwasm process was not verified")
        return 2
    deadline = verified_ns + PRE_WINDOW_NS
    evaluated = empty_eval()
    while True:
        now = time.monotonic_ns()
        upper = min(now, deadline)
        evaluated = evaluate(wasm_path, peer_path, verified_ns, upper)
        if passed(evaluated) or now >= deadline:
            break
        time.sleep(0.1)
    result = "pass" if passed(evaluated) else "timeout"
    finish_ns = min(time.monotonic_ns(), deadline) if result == "timeout" else time.monotonic_ns()
    write_gate(name, result, start_utc, verified_ns, utc_now(), finish_ns, evaluated,
               deadline_mono_ns=deadline, peer_ready=evaluated["peer_ready"],
               criterion="10 distinct ordered ID+payload round trips within 60 seconds")
    if result == "pass":
        (RAW / "gate-pass.ok").write_text(
            f"gate_pass_host_mono_ns={time.monotonic_ns()}\n"
            f"distinct_roundtrip_ids={','.join(str(item['id']) for item in evaluated['complete'])}\n",
            encoding="utf-8")
        return 0
    return 1


def run_baseline():
    name = "no-cr-baseline"
    marker = RAW / "gate-pass.ok"
    if not marker.is_file():
        raise SystemExit("pre-checkpoint evidence gate did not pass; refusing baseline")
    wasm_path, peer_path = RAW / "wasm-checkpoint.log", RAW / "peer-native.log"
    published = parse_events(read(wasm_path), PUBLISH_RE, "publish")
    if not published:
        raise SystemExit("no Wasm publish events at baseline start")
    max_start_id = max(event["id"] for event in published)
    start_utc, start_ns = utc_now(), time.monotonic_ns()
    deadline = start_ns + BASELINE_WINDOW_NS
    while time.monotonic_ns() < deadline:
        time.sleep(min(0.25, max(0.0, (deadline - time.monotonic_ns()) / 1e9)))
    finish_ns = time.monotonic_ns()
    evaluated = evaluate(wasm_path, peer_path, start_ns, deadline, max_start_id)
    result = "pass" if passed(evaluated) else "fail"
    write_gate(name, result, start_utc, start_ns, utc_now(), finish_ns, evaluated,
               deadline_mono_ns=deadline, peer_ready=evaluated["peer_ready"],
               start_max_publish_id=max_start_id,
               criterion="10 distinct new ordered ID+payload round trips within 30 seconds")
    return 0 if result == "pass" else 1


def run_post(checkpoint_max):
    name = "postcr-gate"
    wasm_path, peer_path = RAW / "wasm-restore.log", RAW / "peer-native.log"
    gate_start_utc, gate_start_ns = utc_now(), time.monotonic_ns()
    verified_ns = wait_for_verified(wasm_path, RAW / "wasm-restore.status",
                                    gate_start_ns, VERIFY_WAIT_NS)
    if verified_ns is None:
        write_gate(name, "restore_process_verification_failed", gate_start_utc,
                   gate_start_ns, utc_now(), time.monotonic_ns(), empty_eval(),
                   checkpoint_max=checkpoint_max)
        return 2
    deadline = verified_ns + POST_WINDOW_NS
    evaluated = empty_eval()
    while True:
        now = time.monotonic_ns()
        upper = min(now, deadline)
        evaluated = evaluate(wasm_path, peer_path, verified_ns, upper, checkpoint_max)
        if passed(evaluated) or now >= deadline:
            break
        time.sleep(0.1)
    result = "pass" if passed(evaluated) else "timeout"
    finish_ns = min(time.monotonic_ns(), deadline) if result == "timeout" else time.monotonic_ns()
    write_gate(name, result, gate_start_utc, verified_ns, utc_now(), finish_ns, evaluated,
               deadline_mono_ns=deadline, peer_ready=evaluated["peer_ready"],
               checkpoint_max=checkpoint_max,
               criterion="10 distinct post-restore publish IDs > N with the same bodies and ordered events within 90 seconds")
    return 0 if result == "pass" else 1


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "pre":
        return run_pre()
    if len(sys.argv) == 2 and sys.argv[1] == "baseline":
        return run_baseline()
    if len(sys.argv) == 3 and sys.argv[1] == "post" and sys.argv[2].isdigit():
        return run_post(int(sys.argv[2]))
    raise SystemExit("usage: roundtrip_evidence_gate.py pre|baseline|post [CHECKPOINT_MAX]")


if __name__ == "__main__":
    raise SystemExit(main())
