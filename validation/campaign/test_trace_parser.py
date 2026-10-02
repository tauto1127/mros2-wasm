#!/usr/bin/env python3
"""Offline contract tests for the literal trace dump ABI consumed by run.py."""
import importlib.util
from pathlib import Path
import threading
import unittest

RUNNER = Path(__file__).with_name('run.py')
spec = importlib.util.spec_from_file_location('campaign_runner', RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class TraceParserTests(unittest.TestCase):
    def report(self, *, lost=0, max_active=1):
        lines = [
            'RTPS_TRACE seq=0 kind=1 result=4 current=0 applied=0 detail=4 aux=9 thread=1234',
            'RTPS_TRACE seq=1 kind=2 result=0 current=0 applied=0 detail=0 aux=0 thread=1234',
            'RTPS_TRACE seq=2 kind=3 result=4 current=0 applied=0 detail=0 aux=1 thread=1234',
            'RTPS_TRACE seq=3 kind=4 result=0 current=0 applied=0 detail=0 aux=1 thread=1234',
            'RTPS_TRACE seq=4 kind=5 result=0 current=0 applied=0 detail=0 aux=1 thread=1234',
            f'RTPS_TRACE_METRICS attempts=1 winners=1 busy=0 failed=0 outcomes=1 probe_completions=1 active=0 max_active={max_active} lost={lost} lockfree=1',
        ]
        session = runner.Session.__new__(runner.Session)
        session.events = []
        session.lock = threading.Lock()
        for line in lines:
            event = runner.parse_trace_line(line)
            self.assertIsNotNone(event)
            session.events.append(event)
        return session.trace_report()

    def test_actual_dump_schema_ready(self):
        report = self.report()
        self.assertEqual(report['telemetry_status'], 'READY', report['not_pass_reasons'])
        self.assertEqual(report['records'][0]['thread_id'], 1234)

    def test_nonzero_observer_loss_rejected(self):
        report = self.report(lost=1)
        self.assertEqual(report['telemetry_status'], 'NOT PASS')
        self.assertIn('observer loss/overflow nonzero', report['not_pass_reasons'])

    def test_probe_overlap_violation_rejected(self):
        report = self.report(max_active=2)
        self.assertEqual(report['telemetry_status'], 'NOT PASS')
        self.assertIn('measured probe overlap max_active > 1', report['not_pass_reasons'])


if __name__ == '__main__':
    unittest.main()
