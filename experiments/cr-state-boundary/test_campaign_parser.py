#!/usr/bin/env python3
import importlib.util
import sys
import tempfile
from pathlib import Path

CAMPAIGN = Path(__file__).with_name("campaign.py")
spec = importlib.util.spec_from_file_location("campaign", CAMPAIGN)
campaign = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = campaign
spec.loader.exec_module(campaign)

sample = """host_utc=2026-10-04T00:00:00Z host_mono_ns=100 [CR-STATE] loop id=14 guest_before=0xa500000d host_before=0xa500000d
host_utc=2026-10-04T00:00:01Z host_mono_ns=110 [CR-STATE] armed id=14 value=0xa500000e
host_utc=2026-10-04T00:00:02Z host_mono_ns=120 [CR-STATE] netif_refresh default=0x100 self=0x100 same=1 stored=0x030012ac probed=0x060012ac pending=1
host_utc=2026-10-04T00:00:03Z host_mono_ns=130 [CR-STATE] netif_refresh default=0x100 self=0x100 same=1 stored=0x060012ac probed=0x060012ac pending=0
host_utc=2026-10-04T00:00:04Z host_mono_ns=140 netif_wasm: dynamic ip=0x060012ac mask=0x00ffffff
"""

with tempfile.TemporaryDirectory() as td:
    path = Path(td) / "log.txt"
    path.write_text(sample)
    parsed = campaign.parse_state_log(path)

assert parsed["loops"][0]["guest"] == 0xA500000D
assert parsed["loops"][0]["host"] == 0xA500000D
assert parsed["armed"][0]["value"] == 0xA500000E
assert parsed["refresh"][0]["same"] == 1
assert campaign.ip_text(parsed["refresh"][0]["stored"]) == "172.18.0.3"
assert campaign.ip_text(parsed["refresh"][0]["probed"]) == "172.18.0.6"
assert campaign.ip_text(parsed["dynamic"][0]["value"]) == "172.18.0.6"
print("parser synthetic checks: PASS")
assert any(item["mono"] > parsed["refresh"][0]["mono"] and campaign.ip_text(item["stored"]) == "172.18.0.6" for item in parsed["refresh"])
