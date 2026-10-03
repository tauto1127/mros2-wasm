import json
import tempfile
import unittest
from pathlib import Path

from validation.campaign import run


class TraceReportSerializationTest(unittest.TestCase):
    def test_persist_trace_report_writes_json_with_a_real_newline(self):
        with tempfile.TemporaryDirectory(prefix="trace-report-json-") as directory:
            session = object.__new__(run.Session)
            session.root = Path(directory)
            session.trace_report = lambda: {"telemetry_status": "NOT PASS", "records": []}

            session.persist_trace_report()
            path = Path(directory) / "trace-report.json"
            raw = path.read_bytes()
            self.assertTrue(raw.endswith(b"\n"), repr(raw[-4:]))
            self.assertFalse(raw.endswith(b"\\n"), repr(raw[-4:]))
            self.assertEqual(json.loads(raw), {"telemetry_status": "NOT PASS", "records": []})


if __name__ == "__main__":
    unittest.main()
