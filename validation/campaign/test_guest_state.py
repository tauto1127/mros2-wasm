#!/usr/bin/env python3
"""Offline assertions for current-app actual guest-state observer records."""
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import threading
import unittest

RUNNER = Path(__file__).with_name('run.py')
spec = importlib.util.spec_from_file_location('campaign_runner_guest', RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class GuestStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.memory = root / 'state' / 'phase-01' / 'main-memory.img'
        self.memory.parent.mkdir(parents=True)
        self.image = bytearray(96)
        self.image[0:4] = struct.pack('<I', 0x20)  # saved netif_default pointer
        self.image[4:8] = struct.pack('<I', 0x030012ac)  # 172.18.0.3 in WASM little-endian u32
        self.image[8:12] = struct.pack('<I', 0x0000ffff)
        self.image[12:16] = struct.pack('<I', 0x030012ac)  # applied IP
        self.image[16:28] = bytes.fromhex('00112233445566778899aabb')
        self.image[28:44] = bytes(12) + bytes.fromhex('ac120003')
        self.image[44:48] = struct.pack('<I', 7400)
        self.image[48:52] = struct.pack('<i', 1)
        self.endpoint_guid = bytes.fromhex('00112233445566778899aabb01020304')
        self.image[52:68] = self.endpoint_guid
        self.memory.write_bytes(self.image)
        self.raw = root / 'raw'
        self.raw.mkdir()
        self.log = self.raw / 'observer' / 'trace-observer.log'
        self.log.parent.mkdir()
        self.c = {'schema': runner.GUEST_STATE_SCHEMA, 'part': 'c', 'checkpoint_seq': 7,
            'default_ptr_field_addr': '0x0', 'default_ptr': '0x20',
            'ip_field_addr': '0x4', 'ip_value': '0x030012ac',
            'netmask_field_addr': '0x8', 'netmask_value': '0x0000ffff',
            'ip_semantics': 'network-order IPv4 bytes'}
        self.cpp = {'schema': runner.GUEST_STATE_SCHEMA, 'part': 'cpp', 'checkpoint_seq': 7,
            'current_ip_value': '0x030012ac', 'applied_field_addr': '0xc', 'applied_value': '0x030012ac',
            'guid_prefix_addr': '0x10', 'guid_prefix': '00112233445566778899aabb',
            'selection_absent': False, 'user_writer_count': 1, 'user_reader_count': 0,
            'selected_locator': {'role': 'writer', 'address_field_addr': '0x1c',
                'address_bytes': '00' * 12 + 'ac120003', 'port_field_addr': '0x2c',
                'port_value': '0x00001ce8', 'kind_field_addr': '0x30', 'kind_value': 1,
                'endpoint_guid_addr': '0x34', 'endpoint_guid': '00112233445566778899aabb01020304'}}
        self.old_size = runner.MEMORY_BYTES
        runner.MEMORY_BYTES = len(self.image)

    def tearDown(self):
        runner.MEMORY_BYTES = self.old_size
        self.tmp.cleanup()

    def invoke(self):
        records = [self.c, self.cpp]
        self.log.write_text('\n'.join(json.dumps(r) for r in records) + '\n')
        session = runner.Session.__new__(runner.Session)
        session.raw = self.raw
        session.states = self.memory.parent.parent
        return session.guest_state(self.raw)

    def test_actual_observer_output_matches_image_and_network_bytes(self):
        report = self.invoke()
        self.assertTrue(report['matches_checkpoint_image'])
        self.assertEqual(report['participant_guid_prefix']['bytes'], self.cpp['guid_prefix'])
        self.assertEqual(report['selected_locator']['address_bytes'][-8:], 'ac120003')

    def test_observer_image_address_out_of_bounds_rejected(self):
        self.c['ip_field_addr'] = '0x5f'
        with self.assertRaisesRegex(RuntimeError, 'outside saved guest memory'):
            self.invoke()

    def test_little_endian_value_mismatch_rejected(self):
        self.c['ip_value'] = '0xac120003'
        with self.assertRaisesRegex(RuntimeError, 'little-endian bytes'):
            self.invoke()

    def test_actual_observer_output_parser_rejects_malformed_record(self):
        self.log.write_text('{broken-json}\n')
        session = runner.Session.__new__(runner.Session)
        session.raw = self.raw
        session.states = self.memory.parent.parent
        with self.assertRaisesRegex(RuntimeError, 'malformed actual guest-state'):
            session.guest_state(self.raw)

    def test_selected_locator_value_mismatch_rejected(self):
        self.cpp['selected_locator']['address_bytes'] = '00' * 12 + 'ac120004'
        with self.assertRaisesRegex(RuntimeError, 'checkpoint image'):
            self.invoke()

    def test_converged_but_wrong_planned_ip_is_rejected_against_image(self):
        self.log.write_text(json.dumps(self.c)+'\n'+json.dumps(self.cpp)+'\n')
        session = runner.Session.__new__(runner.Session)
        session.raw = self.raw
        session.states = self.memory.parent.parent
        with self.assertRaisesRegex(RuntimeError, 'differs from planned phase IP'):
            session.guest_state(self.raw, expected_ip='172.18.0.4')

    def test_matching_planned_ip_is_recorded_with_image_verification(self):
        self.log.write_text(json.dumps(self.c)+'\n'+json.dumps(self.cpp)+'\n')
        session = runner.Session.__new__(runner.Session)
        session.raw = self.raw
        session.states = self.memory.parent.parent
        report = session.guest_state(self.raw, expected_ip='172.18.0.3')
        self.assertEqual(report['expected_phase_ip'], '172.18.0.3')

    def test_fresh_record_pair_must_follow_roundtrip_collector_watermark(self):
        self.log.write_text(json.dumps(self.c)+'\n'+json.dumps(self.cpp)+'\n')
        session = runner.Session.__new__(runner.Session)
        session.raw = self.raw
        session.events = [('callback',i,100+i,'wasm') for i in range(1,11)]
        session.lock = threading.Lock()
        def append_fresh():
            import time
            time.sleep(.05)
            with self.log.open('a') as stream:
                for record in (self.c,self.cpp):
                    stream.write(json.dumps(record)+'\n')
                    stream.flush()
        thread=threading.Thread(target=append_fresh); thread.start()
        report=session.wait_guest_state_observation(self.raw,list(range(1,11)),timeout=2)
        thread.join()
        self.assertTrue(report['fresh_after_roundtrip_gate'])
        self.assertIn('file-byte ordering only',report['ordering_claim'])

    def test_fresh_converged_but_wrong_planned_ip_is_rejected(self):
        self.log.write_text('')
        session = runner.Session.__new__(runner.Session)
        session.raw = self.raw
        session.events = [('callback',i,100+i,'wasm') for i in range(1,11)]
        session.lock = threading.Lock()
        def append_fresh():
            import time
            time.sleep(.05)
            with self.log.open('a') as stream:
                for record in (self.c,self.cpp):
                    stream.write(json.dumps(record)+'\n')
                    stream.flush()
        thread=threading.Thread(target=append_fresh); thread.start()
        with self.assertRaisesRegex(RuntimeError, 'differs from planned phase IP'):
            session.wait_guest_state_observation(self.raw,list(range(1,11)),timeout=2,expected_ip='172.18.0.4')
        thread.join()


if __name__ == '__main__':
    unittest.main()
