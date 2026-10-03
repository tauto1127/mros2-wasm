import json
import tempfile
import unittest
from pathlib import Path

from validation.campaign import run


class RuntimePinTest(unittest.TestCase):
    def test_new_restore_fix_runtime_is_campaign_default_and_pin(self):
        self.assertEqual(
            str(run.RUNTIME_DEFAULT),
            "/tmp/wamr-parent-restore-park-fix-20261002/build-fixed/iwasm",
        )
        self.assertEqual(
            run.HASHES["runtime"],
            "70bfcdc4b109041deec3eef4677a605a3fb8d5e03cf16fb026ca4ca8a85938f3",
        )

    def test_normal_control_is_explicit_and_no_cr_only(self):
        args = run.parse_args(["--mode", "no-cr", "--normal-no-cr-control"])
        self.assertTrue(args.normal_no_cr_control)
        self.assertEqual(args.mode, "no-cr")
        self.assertEqual(args.no_cr_ip, "172.18.0.6")

    def test_normal_control_does_not_waive_t11_hash_without_manifest(self):
        if not all(path.is_file() for path in (run.APP_DEFAULT, run.RUNTIME_DEFAULT, run.PEER_DEFAULT)):
            self.skipTest('pinned T11 artifacts unavailable')
        with self.assertRaisesRegex(SystemExit,'requires --normal-build-manifest'):
            run.main(['--app',str(run.APP_DEFAULT),'--runtime',str(run.RUNTIME_DEFAULT),
                      '--peer',str(run.PEER_DEFAULT),'--mode','no-cr','--normal-no-cr-control','--dry-run'])

    def test_normal_build_manifest_pins_artifacts_and_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            files={name:root/name for name in ('app.wasm','iwasm','peer','source.cpp')}
            for path in files.values(): path.write_bytes(path.name.encode())
            manifest={
                'schema':'normal-wasm-build-provenance-v1',
                'status':'clean normal build passed',
                'artifacts':{key:{'path':str(files[name].resolve()),'sha256':run.digest(files[name])}
                             for key,name in (('app','app.wasm'),('runtime','iwasm'),('peer','peer'))},
                'sources':[{'path':str(files['source.cpp']),'sha256':run.digest(files['source.cpp'])}],
                'configure_command':'cmake configure','build_command':'cmake build',
            }
            path=root/'manifest.json'; path.write_text(json.dumps(manifest))
            self.assertEqual(run.validate_normal_build_manifest(path,files['app.wasm'],files['iwasm'],files['peer']),manifest)
            files['source.cpp'].write_text('changed')
            with self.assertRaisesRegex(ValueError,'source pin mismatch'):
                run.validate_normal_build_manifest(path,files['app.wasm'],files['iwasm'],files['peer'])


if __name__ == "__main__":
    unittest.main()
