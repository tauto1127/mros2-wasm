import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name('guest_state_output_smoke.c')
RUNNER = Path(__file__).with_name('run.py')
spec = importlib.util.spec_from_file_location('campaign_runner', RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
RUNTIME = Path('/tmp/mros2-wasm-no-udp-recover-experiment-build-03/runtime/iwasm')
SYSROOT = Path('/home/osslab/wasi-sysroot')


def assert_records(path):
    records = {'cpp': [], 'c': []}; events = []; metrics = []
    for line in path.read_text().splitlines():
        if line.startswith('{'):
            value = json.loads(line)
            if value.get('part') not in records: raise AssertionError(f'unexpected JSON record: {value}')
            records[value['part']].append(value['id'])
        elif line.startswith('RTPS_TRACE seq='):
            parsed = runner.parse_trace_line(line)
            if not parsed or parsed[0] != 'trace': raise AssertionError(f'malformed trace event: {line}')
            events.append(parsed[1])
        elif line.startswith('RTPS_TRACE_METRICS '):
            parsed = runner.parse_trace_line(line)
            if not parsed or parsed[0] != 'trace_metrics': raise AssertionError(f'malformed metrics row: {line}')
            metrics.append(parsed[1])
        else:
            raise AssertionError(f'partial/interleaved observer write: {line!r}')
    expected = list(range(1000))
    for part, ids in records.items():
        if len(ids) != 1000 or sorted(ids) != expected:
            raise AssertionError(f'incomplete {part} guest-state records: {len(ids)}')
    if len(events) != 1000 or sorted(row['seq'] for row in events) != expected:
        raise AssertionError(f'incomplete/interleaved trace events: {len(events)}')
    if len(metrics) != 1000 or sorted(row['batch'] for row in metrics) != expected:
        raise AssertionError(f'incomplete/interleaved metrics rows: {len(metrics)}')


class GuestStateOutputTest(unittest.TestCase):
    def test_concurrent_trace_metrics_and_guest_state_share_atomic_append_fd(self):
        with tempfile.TemporaryDirectory(prefix='trace-observer-stdio-') as temp:
            directory = Path(temp)
            binary = directory / 'observer-output-smoke'
            output = directory / 'trace-observer.log'
            subprocess.run(['cc', '-std=c11', '-D_POSIX_C_SOURCE=200809L', '-Wall', '-Wextra',
                            '-pthread', str(SOURCE), '-o', str(binary)], check=True)
            subprocess.run([str(binary), str(output)], stdout=subprocess.DEVNULL, check=True)
            assert_records(output)

    def test_wasi_threads_runtime_shared_fd_concurrent_output(self):
        if not RUNTIME.is_file() or not SYSROOT.is_dir():
            self.skipTest('pinned runtime or T10 thread-enabled WASI sysroot is unavailable')
        with tempfile.TemporaryDirectory(prefix='trace-observer-wasi-') as temp:
            directory = Path(temp)
            wasm = directory / 'observer-output-smoke.wasm'
            output = directory / 'trace-observer.log'
            subprocess.run(['/opt/wasi-sdk-21/bin/clang', '--target=wasm32-wasi-threads',
                            f'--sysroot={SYSROOT}', '-pthread', '-O0', '-g', str(SOURCE),
                            '-Wl,--shared-memory,--initial-memory=134217728,--max-memory=134217728',
                            '-o', str(wasm)], check=True)
            subprocess.run([str(RUNTIME), '--max-threads=6', f'--map-dir=/observer::{directory}',
                            str(wasm), '/observer/trace-observer.log'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, text=True)
            assert_records(output)


if __name__ == '__main__':
    unittest.main()
