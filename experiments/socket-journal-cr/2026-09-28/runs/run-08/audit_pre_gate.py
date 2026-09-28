#!/usr/bin/env python3
"""Summarize distinct same-ID/body stages inside the failed pre-C/R window."""

from pathlib import Path
import re


RUN = Path(__file__).resolve().parent
RAW = RUN / "raw"
STAMP = re.compile(r"\bhost_mono_ns=(\d+)\b")
PATTERNS = {
    "wasm_publish": ("wasm-checkpoint.log",
                     re.compile(r"APP publish_begin topic=/to_linux id=(\d+) payload='([^']*)'")),
    "native_receive": ("peer-native.log",
                        re.compile(r"event=peer_receive topic=/to_linux id=(\d+) payload='([^']*)'")),
    "native_echo_return": ("peer-native.log",
                           re.compile(r"event=peer_echo_publish_return topic=/to_stm id=(\d+) payload='([^']*)'")),
    "wasm_callback": ("wasm-checkpoint.log",
                      re.compile(r"APP callback topic=/to_stm id=(\d+) payload='([^']*)'")),
}


def read_status():
    return dict(line.split("=", 1) for line in (RAW / "roundtrip-gate.status").read_text().splitlines()
                if "=" in line)


def load_events(name, lower, upper):
    filename, pattern = PATTERNS[name]
    content = (RAW / filename).read_text(encoding="utf-8", errors="replace")
    events = []
    for line in content.splitlines():
        match = pattern.search(line)
        stamp = STAMP.search(line)
        if not match or not stamp:
            continue
        mono = int(stamp.group(1))
        if lower <= mono <= upper:
            events.append((int(match.group(1)), match.group(2), mono, line))
    return events


def main():
    status = read_status()
    lower, upper = int(status["start_mono_ns"]), int(status["deadline_mono_ns"])
    events = {name: load_events(name, lower, upper) for name in PATTERNS}
    keys = {name: {(msg_id, payload) for msg_id, payload, _mono, _line in items}
            for name, items in events.items()}
    publish_receive = keys["wasm_publish"] & keys["native_receive"]
    publish_receive_echo = publish_receive & keys["native_echo_return"]
    all_four = publish_receive_echo & keys["wasm_callback"]

    ids = sorted({msg_id for msg_id, _payload in keys["wasm_publish"]})
    stage_ids = {stage: sorted({msg_id for msg_id, _payload in pairs})
                 for stage, pairs in keys.items()}
    publish_ids = {msg_id for msg_id, _payload in keys["wasm_publish"]}
    receive_ids = {msg_id for msg_id, _payload in keys["native_receive"]}
    echo_ids = {msg_id for msg_id, _payload in keys["native_echo_return"]}
    publish_only_ids = sorted(publish_ids - receive_ids)
    native_only_ids = sorted((receive_ids & echo_ids) - publish_ids)
    matches = {
        "wasm_publish": keys["wasm_publish"],
        "native_receive": keys["native_receive"],
        "native_echo_return": keys["native_echo_return"],
        "wasm_callback": keys["wasm_callback"],
    }
    complete_ordered = set()
    for msg_id, payload in all_four:
        first = {name: next((mono for event_id, body, mono, _line in events[name]
                             if event_id == msg_id and body == payload), None)
                 for name in PATTERNS}
        if (first["wasm_publish"] < first["native_receive"]
                < first["native_echo_return"] < first["wasm_callback"]):
            complete_ordered.add((msg_id, payload))

    same_body_stages = []
    for msg_id, payload in sorted(publish_receive_echo):
        same_body_stages.append((msg_id, payload))

    out = [
        "---",
        "sources:",
        "  - \"roundtrip-gate.status\"",
        "  - \"wasm-checkpoint.log\"",
        "  - \"peer-native.log\"",
        "---",
        "",
        "# run-08 pre-checkpoint ID/body audit",
        "",
        f"- Gate window monotonic ns: `{lower}` through `{upper}`.",
        f"- Distinct Wasm publish IDs: {len(ids)} ({', '.join(map(str, ids))}).",
        f"- Distinct IDs with the same body at Wasm publish and native receive: {len(publish_receive)}.",
        f"- Distinct IDs with the same body at publish, native receive, and native echo-return logs: {len(publish_receive_echo)}.",
        f"- Distinct IDs with the same body at all four application events: {len(all_four)}.",
        f"- Distinct IDs with all four events strictly ordered by captured host monotonic timestamps: {len(complete_ordered)}.",
        f"- Native receive IDs: {', '.join(map(str, stage_ids['native_receive']))}.",
        f"- Native echo-return IDs: {', '.join(map(str, stage_ids['native_echo_return']))}.",
        f"- Wasm callback IDs: {', '.join(map(str, stage_ids['wasm_callback'])) or 'none'}.",
        f"- Within-window last stages: Wasm-publish-only IDs {', '.join(map(str, publish_only_ids)) or 'none'}; native-receive-and-echo-only IDs {', '.join(map(str, native_only_ids)) or 'none'}; matching records through native echo return IDs {', '.join(str(msg_id) for msg_id, _payload in sorted(publish_receive_echo)) or 'none'}. No ID reached a recorded Wasm callback.",
        "",
        "The native peer source log contains an epoch timestamp and logs `peer_receive` before `peer_echo_publish_return` in the callback. The Wasm `host_mono_ns` prefix is assigned when the host collector reads each output line; it is a collector receipt time, not an application-side timestamp. The gate therefore reports strict full-order success only where all four captured records support that order. No Wasm callback line was observed in this gate window.",
        "",
        "## Same-body native stage records",
        "",
    ]
    for msg_id, payload in same_body_stages:
        out.append(f"- ID {msg_id}: `{payload}`")
    (RAW / "roundtrip-id-analysis.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
