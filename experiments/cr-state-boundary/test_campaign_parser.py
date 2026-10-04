#!/usr/bin/env python3
"""Synthetic parser and state-boundary checks for campaign.py."""

import importlib.util
import sys
import tempfile
from pathlib import Path


CAMPAIGN = Path(__file__).with_name("campaign.py")
spec = importlib.util.spec_from_file_location("campaign", CAMPAIGN)
campaign = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = campaign
spec.loader.exec_module(campaign)


def parse(text):
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "log.txt"
        path.write_text(text, encoding="utf-8")
        return campaign.parse_state_log(path)


changed_log = """host_utc=t0 host_mono_ns=100 [CR-STATE] loop id=15 guest_before=0xa500000e host_before=0x00000000
host_utc=t1 host_mono_ns=101 [CR-STATE] armed id=14 value=0xa500000e
host_utc=t2 host_mono_ns=110 [CR-STATE] netif_refresh default=0x100 self=0x100 same=1 stored=0x030012ac probed=0x060012ac pending=1
host_utc=t3 host_mono_ns=120 [CR-STATE] netif_refresh default=0x100 self=0x100 same=1 stored=0x060012ac probed=0x060012ac pending=0
host_utc=t4 host_mono_ns=130 netif_wasm: dynamic ip=0x060012ac mask=0x00ffffff
"""
parsed = parse(changed_log)
assert parsed["loops"][0]["guest"] == 0xA500000E
assert parsed["loops"][0]["host"] == 0
assert parsed["armed"][0]["value"] == 0xA500000E
assert campaign.unique_latest_armed(parsed["armed"])["id"] == 14
assert campaign.ip_text(parsed["refresh"][0]["stored"]) == "172.18.0.3"
assert campaign.ip_text(parsed["refresh"][0]["probed"]) == "172.18.0.6"
assert campaign.ip_text(parsed["dynamic"][0]["value"]) == "172.18.0.6"

changed = campaign.evaluate_state_observations(
    0xA500000E, "changed", parsed["loops"], parsed["refresh"]
)
assert changed["observations_valid"]
assert changed["guest_state_preserved"] is True
assert changed["native_state_reset"] is True
assert changed["stored_ip_before_refresh"] == "172.18.0.3"
assert changed["probed_ip_before_refresh"] == "172.18.0.6"
assert changed["state_gate_pass"] is True

guest_failed = campaign.evaluate_state_observations(
    0xA500000E,
    "changed",
    [{**parsed["loops"][0], "guest": 0}],
    parsed["refresh"],
)
assert guest_failed["guest_state_preserved"] is False
assert guest_failed["state_gate_pass"] is False

native_persisted = campaign.evaluate_state_observations(
    0xA500000E,
    "changed",
    [{**parsed["loops"][0], "host": 0xA500000E}],
    parsed["refresh"],
)
assert native_persisted["native_state_reset"] is False
assert native_persisted["state_gate_pass"] is False

assert campaign.unique_latest_armed([]) is None
ambiguous = campaign.evaluate_state_observations(
    0xA500000E,
    "changed",
    [parsed["loops"][0], parsed["loops"][0]],
    parsed["refresh"],
)
assert ambiguous["observations_valid"] is False
assert ambiguous["guest_state_preserved"] is None
assert ambiguous["state_gate_pass"] is False

same_refresh = {
    **parsed["refresh"][0],
    "probed": 0x030012AC,
}
same = campaign.evaluate_state_observations(
    0xA500000E, "same", parsed["loops"], [same_refresh]
)
assert same["stored_ip_before_refresh"] == "172.18.0.3"
assert same["probed_ip_before_refresh"] == "172.18.0.3"
assert same["state_gate_pass"] is True

print("parser/state-boundary synthetic checks: PASS")
