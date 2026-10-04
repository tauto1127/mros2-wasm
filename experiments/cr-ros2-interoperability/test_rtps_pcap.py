#!/usr/bin/env python3
import unittest

from rtps_pcap import build_fixture_spdp, iter_pcap, summarize


class RtpsPcapTest(unittest.TestCase):
    def test_fixture_spdp_advertises_destination(self):
        blob = build_fixture_spdp()
        rows = list(iter_pcap(blob))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.vendor, "0d25")
        self.assertEqual(row.writer_id, "000100c2")
        self.assertEqual(row.src, "172.18.0.6")
        self.assertEqual(row.default_unicast_locators[0]["ip"], "172.18.0.6")
        self.assertEqual(row.default_unicast_locators[0]["port"], 7411)
        self.assertEqual(row.metatraffic_unicast_locators[0]["port"], 7410)

    def test_changed_ip_fixture_is_not_class_e(self):
        summary = summarize(
            build_fixture_spdp(),
            checkpoint_epoch=1_700_000_100,
            restore_epoch=1_700_000_100,
            mode="changed",
        )
        self.assertTrue(summary["guid_continuity"])
        self.assertEqual(summary["post_spdp_default_ips"], ["172.18.0.6"])
        self.assertEqual(summary["classification"]["code"], "advertised")

    def test_missing_spdp_is_mros2_side(self):
        summary = summarize(b"", checkpoint_epoch=0, restore_epoch=0, mode="changed")
        self.assertEqual(summary["classification"]["code"], "E")


if __name__ == "__main__":
    unittest.main()
