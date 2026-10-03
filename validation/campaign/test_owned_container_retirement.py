#!/usr/bin/env python3
"""Actual retirement method tests using a deterministic Docker command fake."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

RUNNER = Path(__file__).with_name('run.py')
spec = importlib.util.spec_from_file_location('campaign_runner_retirement', RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class FakeDocker:
    def __init__(self, *, ip='172.18.0.3', owned=True):
        self.container_id = '0123456789abcdef' * 4
        self.name = 'owned-app'
        self.labels = {runner.LABEL_KEY: 'test-session' if owned else 'foreign-session'}
        self.endpoint = {'NetworkID': runner.NETWORK_ID, 'EndpointID': 'endpoint-id',
            'IPAddress': ip, 'IPPrefixLen': 16, 'Gateway': '172.18.0.1', 'MacAddress': '02:42:ac:12:00:03'}
        self.running = True
        self.commands = []
        self.stop_result = (0, 'stopped', '')
        self.disconnect_result = (0, 'disconnected', '')
        self.replace_after_stop = False
        self.replacement_id = 'fedcba9876543210' * 4
        self.initial_inspect_exception = None
        self.id_inspect_exceptions = {}
        self.id_inspect_count = 0
        self.stop_exception = None
        self.disconnect_exception = None

    def record(self, container_id=None):
        cid = container_id or self.container_id
        networks = {runner.NETWORK: dict(self.endpoint)} if self.endpoint else {}
        actual_id = self.replacement_id if self.replace_after_stop and not self.running and cid == self.container_id else cid
        return {'Id': actual_id, 'Name': '/' + self.name,
            'Config': {'Labels': dict(self.labels)},
            'State': {'Running': self.running, 'Status': 'running' if self.running else 'exited'},
            'NetworkSettings': {'Networks': networks}}

    def __call__(self, args, timeout=60):
        args = list(args)
        self.commands.append((args, timeout))
        if args[0] == 'inspect':
            queried = args[1]
            if queried == self.name and self.initial_inspect_exception is not None:
                exc, self.initial_inspect_exception = self.initial_inspect_exception, None
                raise exc
            if queried == self.container_id:
                self.id_inspect_count += 1
                exc = self.id_inspect_exceptions.pop(self.id_inspect_count, None)
                if exc is not None: raise exc
            if queried not in (self.name, self.container_id):
                return runner.subprocess.CompletedProcess(args, 1, '', 'no such object')
            return runner.subprocess.CompletedProcess(args, 0, json.dumps([self.record()]), '')
        if args[0] == 'stop':
            if args[-1] != self.container_id:
                return runner.subprocess.CompletedProcess(args, 1, '', 'wrong target')
            if self.stop_exception is not None: raise self.stop_exception
            rc, stdout, stderr = self.stop_result
            if rc == 0: self.running = False
            return runner.subprocess.CompletedProcess(args, rc, stdout, stderr)
        if args[:2] == ['network', 'disconnect']:
            if args[-1] != self.container_id:
                return runner.subprocess.CompletedProcess(args, 1, '', 'wrong target')
            if self.disconnect_exception is not None: raise self.disconnect_exception
            rc, stdout, stderr = self.disconnect_result
            if rc == 0: self.endpoint = None
            return runner.subprocess.CompletedProcess(args, rc, stdout, stderr)
        return runner.subprocess.CompletedProcess(args, 97, '', 'unexpected command')


class OwnedContainerRetirementTests(unittest.TestCase):
    def make_session(self, fake):
        session = runner.Session.__new__(runner.Session)
        session.label = 'test-session'
        session.peer_name = 'protected-peer'
        temporary = tempfile.TemporaryDirectory(prefix='retirement-audit-test-')
        self.addCleanup(temporary.cleanup)
        session.root = Path(temporary.name)
        session.args = type('Args', (), {'cleanup_owned_containers': True, 'keep_peer': True})()
        session.names = ['owned-app']
        session.final_pass = False
        session.tail_procs = []
        patcher = patch.object(runner, 'docker', side_effect=fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return session

    def audit(self, session):
        path = session.root / 'container-lifecycle.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_owned_container_stops_then_disconnects_by_full_id_and_audits_both(self):
        fake = FakeDocker()
        session = self.make_session(fake)
        session.stop_owned('owned-app')

        lifecycle = [args for args, _timeout in fake.commands if args[0] in ('stop', 'network')]
        self.assertEqual(lifecycle, [
            ['stop', '--time', '5', fake.container_id],
            ['network', 'disconnect', runner.NETWORK_ID, fake.container_id]])
        self.assertFalse(any(args[0] == 'rm' for args, _timeout in fake.commands))
        rows = self.audit(session)
        self.assertEqual([row['action'] for row in rows], ['stop', 'disconnect'])
        self.assertEqual([row['container_id'] for row in rows], [fake.container_id] * 2)
        self.assertEqual([row['outcome'] for row in rows], ['passed', 'passed'])
        self.assertEqual(rows[0]['returncode'], 0)
        self.assertEqual(rows[0]['stdout'], 'stopped')
        self.assertEqual(rows[0]['status_before']['Running'], True)
        self.assertEqual(rows[0]['status_after']['Running'], False)
        self.assertEqual(rows[0]['endpoint_before']['EndpointID'], 'endpoint-id')
        self.assertIsNone(rows[1]['endpoint_after'])

    def test_failed_stop_is_audited_and_preserves_attachment_without_disconnect(self):
        fake = FakeDocker()
        fake.stop_result = (17, '', 'injected stop failure')
        session = self.make_session(fake)
        with self.assertRaisesRegex(RuntimeError, 'stop failed'):
            session.stop_owned('owned-app')
        row, = self.audit(session)
        self.assertEqual(row['action'], 'stop')
        self.assertEqual(row['container_id'], fake.container_id)
        self.assertEqual(row['returncode'], 17)
        self.assertEqual(row['stderr'], 'injected stop failure')
        self.assertEqual(row['endpoint_before']['EndpointID'], 'endpoint-id')
        self.assertFalse(any(args[0] == 'network' for args, _timeout in fake.commands))
        self.assertFalse(any(args[0] == 'rm' for args, _timeout in fake.commands))
        self.assertIsNotNone(fake.endpoint)

    def test_failed_disconnect_is_audited_and_preserves_network_endpoint(self):
        fake = FakeDocker()
        fake.disconnect_result = (23, '', 'injected disconnect failure')
        session = self.make_session(fake)
        with self.assertRaisesRegex(RuntimeError, 'disconnect failed'):
            session.stop_owned('owned-app')
        rows = self.audit(session)
        self.assertEqual([row['action'] for row in rows], ['stop', 'disconnect'])
        row = rows[-1]
        self.assertEqual(row['container_id'], fake.container_id)
        self.assertEqual(row['returncode'], 23)
        self.assertEqual(row['stderr'], 'injected disconnect failure')
        self.assertEqual(row['endpoint_before']['EndpointID'], 'endpoint-id')
        self.assertEqual(row['endpoint_after']['EndpointID'], 'endpoint-id')
        self.assertIsNotNone(fake.endpoint)
        self.assertFalse(any(args[0] == 'rm' for args, _timeout in fake.commands))

    def test_post_stop_identity_rejection_never_disconnects_replacement(self):
        fake = FakeDocker()
        fake.replace_after_stop = True
        session = self.make_session(fake)
        with self.assertRaisesRegex(RuntimeError, 'identity mismatch'):
            session.stop_owned('owned-app')
        stop = next(args for args, _timeout in fake.commands if args[0] == 'stop')
        self.assertEqual(stop[-1], fake.container_id)
        self.assertFalse(any(args[0] == 'network' for args, _timeout in fake.commands))
        row, = self.audit(session)
        self.assertEqual(row['container_id'], fake.container_id)
        self.assertEqual(row['status_before']['Running'], True)
        self.assertIsNone(row['status_after'])
        self.assertFalse(any(args[0] == 'rm' for args, _timeout in fake.commands))

    def test_actual_ownership_guard_rejects_unowned_container(self):
        fake = FakeDocker(owned=False)
        session = self.make_session(fake)
        with self.assertRaisesRegex(RuntimeError, 'refusing non-owned'):
            session.stop_owned('owned-app')
        rows = self.audit(session)
        self.assertEqual(rows[0]['outcome'], 'rejected')
        self.assertEqual(rows[0]['action'], 'stop')
        self.assertFalse(any(args[0] in ('stop', 'network', 'rm') for args, _timeout in fake.commands))

    def test_actual_peer_guard_refuses_dot_five_before_mutation(self):
        fake = FakeDocker(ip='172.18.0.5')
        fake.name = 'protected-peer'
        session = self.make_session(fake)
        with self.assertRaisesRegex(RuntimeError, 'protected continuous .5 peer'):
            session.stop_owned('protected-peer')
        rows = self.audit(session)
        self.assertEqual(rows[0]['outcome'], 'rejected')
        self.assertEqual(rows[0]['container_id'], fake.container_id)
        self.assertFalse(any(args[0] in ('stop', 'network', 'rm') for args, _timeout in fake.commands))

    @staticmethod
    def timeout_error(argv):
        return runner.subprocess.TimeoutExpired(argv, 3, output='partial-out', stderr='partial-err')

    def test_initial_inspection_timeout_is_persistently_audited(self):
        fake = FakeDocker()
        fake.initial_inspect_exception = self.timeout_error(['docker','inspect','owned-app'])
        session = self.make_session(fake)
        with self.assertRaises(runner.subprocess.TimeoutExpired):
            session.stop_owned('owned-app')
        row, = self.audit(session)
        self.assertEqual(row['action'], 'stop')
        self.assertEqual(row['inspection_exception']['argv'], ['rtk','proxy','docker','inspect','owned-app'])
        self.assertEqual(row['inspection_exception']['exception_type'], 'TimeoutExpired')
        self.assertEqual(row['inspection_exception']['stdout'], 'partial-out')
        self.assertIsNone(row['returncode'])
        self.assertFalse(any(args[0] in ('stop','network','rm') for args,_ in fake.commands))

    def test_pre_stop_id_inspection_transport_error_is_audited_without_mutation(self):
        fake = FakeDocker()
        fake.id_inspect_exceptions[1] = OSError('inspect transport broke')
        session = self.make_session(fake)
        with self.assertRaisesRegex(RuntimeError, 'inspect transport broke'):
            session.stop_owned('owned-app')
        row, = self.audit(session)
        self.assertEqual(row['action'], 'stop')
        self.assertEqual(row['inspection_exception']['exception_type'], 'OSError')
        self.assertIn('inspect transport broke', row['error'])
        self.assertFalse(any(args[0] in ('stop','network','rm') for args,_ in fake.commands))

    def test_post_stop_inspection_without_running_flag_is_not_treated_as_stopped(self):
        fake = FakeDocker()
        original_record = fake.record
        def missing_running(container_id=None):
            record = original_record(container_id)
            if fake.id_inspect_count == 2: record['State'].pop('Running', None)
            return record
        fake.record = missing_running
        session = self.make_session(fake)
        with self.assertRaisesRegex(RuntimeError, 'stop failed'):
            session.stop_owned('owned-app')
        row, = self.audit(session)
        self.assertEqual(row['outcome'], 'failed')
        self.assertIsNone(row['status_after'].get('Running'))
        self.assertIn('status unknown', row['error'])
        self.assertFalse(any(args[0] == 'network' for args,_ in fake.commands))

    def test_post_stop_inspection_timeout_audits_attempt_and_prevents_disconnect(self):
        fake = FakeDocker()
        fake.id_inspect_exceptions[2] = self.timeout_error(['inspect',fake.container_id])
        session = self.make_session(fake)
        with self.assertRaisesRegex(RuntimeError, 'stop failed'):
            session.stop_owned('owned-app')
        row, = self.audit(session)
        self.assertEqual(row['action'], 'stop')
        self.assertEqual(row['command'], ['rtk','proxy','docker','stop','--time','5',fake.container_id])
        self.assertEqual(row['returncode'], 0)
        self.assertEqual(row['stdout'], 'stopped')
        self.assertIsNone(row['status_after'])
        self.assertEqual(row['after_inspection']['exception_type'], 'TimeoutExpired')
        self.assertFalse(any(args[0] == 'network' for args,_ in fake.commands))

    def test_pre_disconnect_inspection_transport_error_is_audited_and_blocks_disconnect(self):
        fake = FakeDocker()
        fake.id_inspect_exceptions[3] = OSError('pre-disconnect transport error')
        session = self.make_session(fake)
        with self.assertRaisesRegex(RuntimeError, 'pre-disconnect transport error'):
            session.stop_owned('owned-app')
        rows = self.audit(session)
        self.assertEqual(rows[0]['outcome'], 'passed')
        self.assertEqual(rows[1]['action'], 'disconnect')
        self.assertEqual(rows[1]['inspection_exception']['exception_type'], 'OSError')
        self.assertIn('pre-disconnect transport error', rows[1]['error'])
        self.assertFalse(any(args[0] == 'network' for args,_ in fake.commands))

    def test_post_disconnect_inspection_timeout_keeps_disconnect_attempt_audit(self):
        fake = FakeDocker()
        fake.id_inspect_exceptions[4] = self.timeout_error(['inspect',fake.container_id])
        session = self.make_session(fake)
        with self.assertRaisesRegex(RuntimeError, 'disconnect failed'):
            session.stop_owned('owned-app')
        rows = self.audit(session)
        row = rows[-1]
        self.assertEqual(row['action'], 'disconnect')
        self.assertEqual(row['command'], ['rtk','proxy','docker','network','disconnect',runner.NETWORK_ID,fake.container_id])
        self.assertEqual(row['returncode'], 0)
        self.assertEqual(row['stdout'], 'disconnected')
        self.assertIsNone(row['status_after'])
        self.assertEqual(row['after_inspection']['exception_type'], 'TimeoutExpired')
        self.assertFalse(any(args[0] == 'rm' for args,_ in fake.commands))

    def test_post_disconnect_malformed_network_snapshot_is_not_treated_as_detached(self):
        fake = FakeDocker()
        original_record = fake.record
        def missing_networks(container_id=None):
            record = original_record(container_id)
            if fake.id_inspect_count == 4: record.pop('NetworkSettings', None)
            return record
        fake.record = missing_networks
        session = self.make_session(fake)
        with self.assertRaisesRegex(RuntimeError, 'disconnect failed'):
            session.stop_owned('owned-app')
        row = self.audit(session)[-1]
        self.assertEqual(row['outcome'], 'failed')
        self.assertEqual(row['endpoint_after'], {'identity_error':'NetworkSettings missing or malformed'})
        self.assertIn('status unknown', row['error'])

    def test_stop_timeout_plus_postinspect_transport_failure_keeps_both_errors(self):
        fake = FakeDocker()
        fake.stop_exception = self.timeout_error(['docker','stop',fake.container_id])
        fake.id_inspect_exceptions[2] = OSError('post-stop inspect transport error')
        session = self.make_session(fake)
        with self.assertRaisesRegex(RuntimeError, 'stop failed'):
            session.stop_owned('owned-app')
        row, = self.audit(session)
        self.assertEqual(row['exception_type'], 'TimeoutExpired')
        self.assertEqual(row['after_inspection']['exception_type'], 'OSError')
        self.assertIn('partial-out', row['stdout'])
        self.assertIn('partial-err', row['stderr'])
        self.assertIsNone(row['status_after'])
        self.assertFalse(any(args[0] == 'network' for args,_ in fake.commands))

    def test_disconnect_transport_error_plus_postinspect_timeout_keeps_both_errors(self):
        fake = FakeDocker()
        fake.disconnect_exception = OSError('disconnect transport error')
        fake.id_inspect_exceptions[4] = self.timeout_error(['inspect',fake.container_id])
        session = self.make_session(fake)
        with self.assertRaisesRegex(RuntimeError, 'disconnect failed'):
            session.stop_owned('owned-app')
        row = self.audit(session)[-1]
        self.assertEqual(row['exception_type'], 'OSError')
        self.assertEqual(row['after_inspection']['exception_type'], 'TimeoutExpired')
        self.assertIsNone(row['returncode'])
        self.assertIsNone(row['status_after'])
        self.assertFalse(any(args[0] == 'rm' for args,_ in fake.commands))

    def test_default_and_failed_campaign_cleanup_preserve_owned_containers(self):
        fake = FakeDocker()
        session = self.make_session(fake)
        session.args.cleanup_owned_containers = False
        session.final_pass = True
        session.cleanup(keep_state=False)
        self.assertEqual(fake.commands, [])
        session.args.cleanup_owned_containers = True
        session.final_pass = False
        session.cleanup(keep_state=False)
        self.assertEqual(fake.commands, [])
        self.assertFalse((session.root / 'container-lifecycle.jsonl').exists())


if __name__ == '__main__':
    unittest.main()
