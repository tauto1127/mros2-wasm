import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from validation.campaign import run


class CheckpointPreflightTest(unittest.TestCase):
    def test_persists_exact_free_bytes_before_checkpoint_and_enforces_floor(self):
        with tempfile.TemporaryDirectory(prefix="checkpoint-preflight-") as directory:
            session = object.__new__(run.Session)
            session.root = Path(directory) / "campaign"
            session.root.mkdir()
            raw = session.root / "raw" / "phase-01"
            raw.mkdir(parents=True)
            required = run.FREE_MIN + 2 * run.MEMORY_BYTES + 1024**2
            free = required + 123456
            with patch.object(run.shutil, "disk_usage", return_value=type("Usage", (), {"free": free})()):
                record = session.persist_checkpoint_preflight(raw)
            self.assertEqual(record["free_bytes"], free)
            self.assertTrue(record["ready"])
            persisted = json.loads((raw / "checkpoint-preflight.json").read_text())
            self.assertEqual(persisted["free_bytes"], free)
            self.assertEqual(persisted["minimum_free_bytes"], run.FREE_MIN)
            self.assertEqual(persisted["required_free_bytes"], required)
            self.assertTrue(persisted["ready"])

    def test_rejects_low_free_space_after_persisting_measurement(self):
        with tempfile.TemporaryDirectory(prefix="checkpoint-preflight-low-") as directory:
            session = object.__new__(run.Session)
            session.root = Path(directory) / "campaign"
            session.root.mkdir()
            raw = session.root / "raw" / "phase-02"
            raw.mkdir(parents=True)
            free = run.FREE_MIN + 2 * run.MEMORY_BYTES + 1024**2 - 1
            with patch.object(run.shutil, "disk_usage", return_value=type("Usage", (), {"free": free})()):
                with self.assertRaisesRegex(RuntimeError, "dump\\+archive\\+3GiB reserve"):
                    session.persist_checkpoint_preflight(raw)
            persisted = json.loads((raw / "checkpoint-preflight.json").read_text())
            self.assertEqual(persisted["free_bytes"], free)
            self.assertFalse(persisted["ready"])


if __name__ == "__main__":
    unittest.main()
