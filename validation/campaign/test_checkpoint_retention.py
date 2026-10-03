import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from validation.campaign import run


class CheckpointRetentionTest(unittest.TestCase):
    def make_session(self, directory, mode="repeated"):
        session = object.__new__(run.Session)
        session.root = Path(directory) / "campaign"
        session.raw = session.root / "raw"
        session.states = session.root / "state"
        session.raw.mkdir(parents=True)
        session.states.mkdir()
        session.args = SimpleNamespace(mode=mode, cleanup_pass_state=False)
        session.hashes = {"app": "app", "runtime": "runtime", "peer": "peer"}
        session.pass_states = []
        session.checkpoint_archives = []
        session.final_pass = False
        return session

    def make_snapshot(self, session, source, phase=1):
        raw = session.raw / f"phase-{phase:02d}"
        raw.mkdir()
        record = session.archive_checkpoint_state(source, raw, phase)
        archive = Path(record["archive_dir"])
        files = [{"path": item["path"], "size": item["size"], "sha256": item["sha256"]}
                 for item in record["files"]]
        manifest_path = raw / "state-manifest.json"
        manifest_path.write_text(json.dumps({"state_dir": str(archive.resolve()), "files": files}) + "\n")
        record["state_manifest_path"] = str(manifest_path.resolve())
        record["state_manifest_sha256"] = run.digest(manifest_path)
        session.persist_checkpoint_archive_record(record)
        return record

    def test_second_working_write_cannot_corrupt_archived_checkpoint_or_manifest(self):
        with tempfile.TemporaryDirectory(prefix="checkpoint-archive-independent-") as directory:
            session = self.make_session(directory)
            source = session.states / "phase-01"
            source.mkdir()
            (source / "memory.img").write_bytes(b"checkpoint-one-memory")
            (source / "socket.img").write_bytes(b"checkpoint-one-socket")
            record = self.make_snapshot(session, source)
            archive = Path(record["archive_dir"])
            before = run.digest(archive / "memory.img")
            self.assertNotEqual((source / "memory.img").stat().st_ino,
                                (archive / "memory.img").stat().st_ino)

            # Simulate the next checkpoint replacing/truncating its mutable /state files.
            (source / "memory.img").write_bytes(b"checkpoint-two-memory")
            (source / "socket.img").write_bytes(b"checkpoint-two-socket")
            self.assertEqual(run.digest(archive / "memory.img"), before)
            self.assertEqual((archive / "memory.img").read_bytes(), b"checkpoint-one-memory")
            self.assertTrue(session.validate_checkpoint_archives(1)["valid"])

    def test_final_verdict_rejects_changed_and_missing_archived_bytes(self):
        for mutation in ("changed", "missing"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(prefix="checkpoint-archive-tamper-") as directory:
                session = self.make_session(directory, mode="changed")
                source = session.states / "phase-01"
                source.mkdir()
                (source / "memory.img").write_bytes(b"image")
                self.make_snapshot(session, source)
                archive_file = Path(session.checkpoint_archives[0]["archive_dir"]) / "memory.img"
                if mutation == "changed":
                    archive_file.write_bytes(b"mutated")
                else:
                    archive_file.unlink()
                (session.root / "trace-report.json").write_text(json.dumps({"telemetry_status": "READY"}))
                result = session.finalize_campaign_verdict(
                    {"telemetry_status": "READY"}, count=1, expected_count=1,
                    assertions_persisted=True, same_ip_asserted=True)
                self.assertNotEqual(result["status"], "PASS")
                self.assertFalse(result["actualCasePassed"])
                self.assertFalse(result["checkpoint_retention"]["valid"])

    def test_partial_archive_copy_failure_cannot_pass(self):
        with tempfile.TemporaryDirectory(prefix="checkpoint-archive-partial-") as directory:
            session = self.make_session(directory)
            source = session.states / "phase-01"
            source.mkdir()
            (source / "memory.img").write_bytes(b"complete-source")
            raw = session.raw / "phase-01"
            raw.mkdir()
            original_copy = run.shutil.copy2

            def partial_then_fail(src, dst):
                Path(dst).write_bytes(b"partial")
                raise OSError("injected archive copy error")

            with patch.object(run.shutil, "copy2", side_effect=partial_then_fail):
                with self.assertRaisesRegex(RuntimeError, "archive"):
                    session.archive_checkpoint_state(source, raw, 1)
            record = session.checkpoint_archives[0]
            self.assertFalse(record["complete"])
            (session.root / "trace-report.json").write_text(json.dumps({"telemetry_status": "READY"}))
            result = session.finalize_campaign_verdict(
                {"telemetry_status": "READY"}, count=1, expected_count=1,
                assertions_persisted=True, same_ip_asserted=True)
            self.assertNotEqual(result["status"], "PASS")
            self.assertFalse(result["actualCasePassed"])
            self.assertTrue(Path(record["archive_dir"]).exists())  # partial evidence is retained

    def test_named_restored_modes_set_actual_pass_only_with_whole_pass(self):
        for mode in ("same", "changed", "repeated"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(prefix="checkpoint-archive-verdict-") as directory:
                session = self.make_session(directory, mode=mode)
                source = session.states / "phase-01"
                source.mkdir()
                (source / "memory.img").write_bytes(b"image")
                self.make_snapshot(session, source)
                (session.root / "trace-report.json").write_text(json.dumps({"telemetry_status": "READY"}))
                result = session.finalize_campaign_verdict(
                    {"telemetry_status": "READY"}, count=1, expected_count=1,
                    assertions_persisted=True, same_ip_asserted=True)
                self.assertEqual(result["status"], "PASS")
                self.assertTrue(result["actualCasePassed"])
                Path(session.checkpoint_archives[0]["archive_dir"], "memory.img").write_bytes(b"changed")
                failed = session.finalize_campaign_verdict(
                    {"telemetry_status": "READY"}, count=1, expected_count=1,
                    assertions_persisted=True, same_ip_asserted=True)
                self.assertNotEqual(failed["status"], "PASS")
                self.assertFalse(failed["actualCasePassed"])


if __name__ == "__main__":
    unittest.main()
