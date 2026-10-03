#!/usr/bin/env python3
"""Boundary, replay, and cleanup regressions for the observer telemetry contract."""
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest

RUNNER = Path(__file__).with_name('run.py')
spec = importlib.util.spec_from_file_location('campaign_runner', RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class TraceParserTests(unittest.TestCase):
    keys = ('read','next','attempts','winners','busy','failed','outcomes','probe_completions',
            'active','max_active','lost','output_failures','lockfree')
    addresses = {key: 0x1000 + i * 4 for i, key in enumerate(keys)}

    def state(self, **updates):
        value = dict.fromkeys(self.keys, 0)
        value.update(lockfree=1, max_active=1)
        value.update(updates)
        return value

    def record(self, prefix, values, **other):
        attrs = dict(values); attrs.update(other); attrs.setdefault('stable',1)
        attrs.update({'addr_' + key: self.addresses[key] for key in self.keys})
        return prefix + ' ' + ' '.join(f'{key}={value if not key.startswith("addr_") else f"0x{value:08x}"}' for key, value in attrs.items()) + '\n'

    def batch(self, events, before, after, batch=1):
        lines=[f'RTPS_TRACE_BATCH_BEGIN batch={batch} read={before["read"]} next={before["next"]}\n',
               self.record('RTPS_TRACE_METRICS',before,batch=batch,edge='before')]
        lines.extend(f"RTPS_TRACE seq={e['seq']} kind={e['kind']} result={e['result']} current={e['current']} applied={e['applied']} detail={e['detail']} aux={e['aux']} thread={e['thread']}\n" for e in events)
        lines.append(self.record('RTPS_TRACE_METRICS',after,batch=batch,edge='after'))
        lines.append(f'RTPS_TRACE_BATCH_END batch={batch} events={len(events)} first={events[0]["seq"] if events else 0} last={events[-1]["seq"] if events else 0} read={after["read"]} next={after["next"]}\n')
        return ''.join(lines)

    def event(self,seq,kind,result=0,current=0,applied=0):
        return {'seq':seq,'kind':kind,'result':result,'current':current,'applied':applied,'detail':0,'aux':0,'thread':1234}

    def run_report(self, contents, windows):
        temp=tempfile.TemporaryDirectory(prefix='trace-window-test-')
        self.addCleanup(temp.cleanup)
        raw=Path(temp.name); observer=raw/'observer'/'trace-observer.log'; observer.parent.mkdir(); observer.write_bytes(contents)
        session=runner.Session.__new__(runner.Session); session.raw=raw; session.observer_windows=windows
        return session.trace_report()

    def basic_window(self, *, lost=0, max_active=1):
        start=self.state()
        final=self.state(read=10,next=10,attempts=1,winners=1,outcomes=1,probe_completions=1,
                         active=0,max_active=max_active,lost=lost)
        events=[self.event(0,1,result=4),self.event(1,2),self.event(2,3,result=3),
                self.event(3,4),self.event(4,5),self.event(5,6),self.event(6,7),
                self.event(7,8),self.event(8,10),self.event(9,11,current=3,applied=3)]
        start_line=self.record('RTPS_TRACE_WINDOW_START',start,stable=1)
        before=dict(final,read=0,next=10)
        data=(start_line+self.batch(events,before,final)).encode()
        window={'window_id':'checkpoint-1-pid12','role':'checkpoint','pid':12,'pid_start_ticks':'99',
                'start_offset':0,'end_offset':len(data),'expected_image_baseline':None,'image_trace_baseline':None}
        return data,[window]

    def test_closed_process_window_uses_shared_channel_and_actual_counter_delta(self):
        data,windows=self.basic_window(); report=self.run_report(data,windows)
        self.assertEqual(report['telemetry_status'],'READY',report['not_pass_reasons'])
        self.assertEqual(report['windows'][0]['counter_deltas']['attempts'],1)
        self.assertEqual(report['windows'][0]['pending_batch_resolution'],
                         'closed by actual process/image initial/final scalar deltas')
        self.assertEqual(report['output_channel'],'validated append-only shared observer FD')
        self.assertFalse(report['stdout_trace_fallback'])

    def test_stdout_interleaved_trace_text_is_not_a_telemetry_source(self):
        self.assertIsNone(runner.parse_trace_line('host_utc=... RTPS_TRACE seq=120 kind=6 result=3 current=1 applied=1 detail=0 aux=0 thread=12'))

    def test_nonzero_loss_and_overlap_are_not_waived(self):
        for kwargs, phrase in (({'lost':1},'loss or observer write failure'),({'max_active':2},'measured overlap exceeds one')):
            with self.subTest(kwargs=kwargs):
                data,windows=self.basic_window(**kwargs); report=self.run_report(data,windows)
                self.assertEqual(report['telemetry_status'],'NOT PASS')
                self.assertTrue(any(phrase in reason for reason in report['not_pass_reasons']))

    def test_restore_boundary_replay_is_attributed_to_saved_checkpoint_tail(self):
        zero=self.state(); image=self.state(read=0,next=2,attempts=1,winners=1,outcomes=1)
        checkpoint_start=self.record('RTPS_TRACE_WINDOW_START',zero,stable=1)
        checkpoint_batch=self.batch([],zero,zero)
        checkpoint_data=(checkpoint_start+checkpoint_batch).encode()
        restore_start=self.record('RTPS_TRACE_WINDOW_START',image,stable=1)
        final=self.state(read=10,next=10,attempts=1,winners=1,outcomes=1,probe_completions=1)
        events=[self.event(0,2),self.event(1,3,result=3),self.event(2,4),self.event(3,5),
                self.event(4,1,result=4),self.event(5,6),self.event(6,7),self.event(7,8),
                self.event(8,10),self.event(9,11,current=3,applied=3)]
        before=dict(final,read=0,next=10)
        restore_data=(restore_start+self.batch(events,before,final,batch=2)).encode()
        data=checkpoint_data+restore_data
        image_baseline={'window_id':'checkpoint-1-pid12','values':image,
                        'addresses':{key:f'0x{address:08x}' for key,address in self.addresses.items()}}
        windows=[{'window_id':'checkpoint-1-pid12','role':'checkpoint','pid':12,'pid_start_ticks':'99',
                  'start_offset':0,'end_offset':len(checkpoint_data),'expected_image_baseline':None,
                  'image_trace_baseline':image_baseline},
                 {'window_id':'restore-2-pid17','role':'restore','pid':17,'pid_start_ticks':'110',
                  'start_offset':len(checkpoint_data),'end_offset':len(data),
                  'expected_image_baseline':image_baseline,'image_trace_baseline':None}]
        report=self.run_report(data,windows)
        self.assertEqual(report['telemetry_status'],'READY',report['not_pass_reasons'])
        self.assertEqual(report['replay_count'],2)
        self.assertEqual(report['windows'][1]['replays'][0]['kind'],'checkpoint-pending-tail')
        self.assertEqual(report['windows'][0]['counter_deltas']['attempts'],1)

    def test_injected_telemetry_failure_persists_evidence_and_never_cleans_payload(self):
        with tempfile.TemporaryDirectory(prefix='cleanup-failure-') as temp:
            root=Path(temp); state=root/'states'/'phase-01'; state.mkdir(parents=True)
            (state/'main-memory.img').write_bytes(b'preserved-payload')
            raw=root/'phase-01'; raw.mkdir()
            manifest=raw/'state-manifest.json'; manifest.write_text(json.dumps({'state_dir':str(state),'files':[]}))
            assertions=raw/'assertions.json'; assertions.write_text(json.dumps({'roundtrip':'PASS','image':'PASS'}))
            session=runner.Session.__new__(runner.Session); session.root=root; session.states=root/'states'
            session.args=types.SimpleNamespace(cleanup_pass_state=True); session.final_pass=False
            session.pass_states=[{'state':str(state),'raw':str(raw),'manifest':str(manifest),
                'assertions':str(assertions),'manifest_sha256':runner.digest(manifest),
                'assertions_sha256':runner.digest(assertions)}]
            (root/'trace-report.json').write_text(json.dumps({'telemetry_status':'NOT PASS','not_pass_reasons':['injected sequence/counter failure']}))
            session.persist_campaign_verdict({'status':'NOT PASS; telemetry injected failure','roundtrip':'PASS','image':'PASS'})
            self.assertTrue((state/'main-memory.img').is_file())
            self.assertTrue((root/'failure.json').is_file())
            failure=json.loads((root/'failure.json').read_text())
            self.assertIn('injected sequence/counter failure',failure['telemetry_not_pass_reasons'])
            self.assertFalse((root/'pass-state-cleanup.json').exists())

    def test_pass_cleanup_opt_in_writes_hash_manifest_before_removing_exact_owned_files(self):
        with tempfile.TemporaryDirectory(prefix='cleanup-opt-in-pass-') as temp:
            root=Path(temp); state=root/'states'/'phase-01'; state.mkdir(parents=True)
            payload=state/'memory.img'; payload.write_bytes(b'owned-payload'); payload_sha=runner.digest(payload)
            raw=root/'phase-01'; raw.mkdir()
            manifest=raw/'state-manifest.json'; manifest.write_text(json.dumps({'state_dir':str(state),
                'files':[{'path':'memory.img','size':payload.stat().st_size,'sha256':runner.digest(payload)}]}))
            assertions=raw/'assertions.json'; assertions.write_text(json.dumps({'roundtrip':'PASS','image':'PASS'}))
            session=runner.Session.__new__(runner.Session); session.root=root; session.states=root/'states'
            session.args=types.SimpleNamespace(cleanup_pass_state=True); session.final_pass=True
            session.pass_states=[{'state':str(state),'raw':str(raw),'manifest':str(manifest),
                'assertions':str(assertions),'manifest_sha256':runner.digest(manifest),
                'assertions_sha256':runner.digest(assertions)}]
            (root/'trace-report.json').write_text(json.dumps({'telemetry_status':'READY'}))
            session.verify_manifest=lambda owned, source: {'state_dir':str(owned)}
            session.persist_campaign_verdict({'status':'PASS'})
            cleanup=json.loads((root/'pass-cleanup-manifest.json').read_text())
            self.assertEqual(cleanup['owned_paths'][0]['sha256'],payload_sha)
            self.assertFalse(state.exists())
            self.assertTrue((root/'pass-state-cleanup.json').is_file())

    def test_cleanup_requires_opt_in_even_after_persisted_pass(self):
        with tempfile.TemporaryDirectory(prefix='cleanup-opt-in-') as temp:
            root=Path(temp); state=root/'states'/'phase-01'; state.mkdir(parents=True)
            payload=state/'memory.img'; payload.write_bytes(b'payload')
            raw=root/'phase-01'; raw.mkdir()
            manifest=raw/'state-manifest.json'; manifest.write_text('{}')
            assertions=raw/'assertions.json'; assertions.write_text('{}')
            session=runner.Session.__new__(runner.Session); session.root=root; session.states=root/'states'
            session.args=types.SimpleNamespace(cleanup_pass_state=False); session.final_pass=True
            session.pass_states=[{'state':str(state),'raw':str(raw),'manifest':str(manifest),
                'assertions':str(assertions),'manifest_sha256':runner.digest(manifest),
                'assertions_sha256':runner.digest(assertions)}]
            (root/'result.json').write_text(json.dumps({'status':'PASS'}))
            (root/'trace-report.json').write_text(json.dumps({'telemetry_status':'READY'}))
            session.cleanup_pass_state_files()
            self.assertEqual(payload.read_bytes(),b'payload')
            self.assertFalse((root/'pass-state-cleanup.json').exists())


if __name__ == '__main__':
    unittest.main()
