"""Session ownership and fragmented delivery using real local sockets, no TV audio."""
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1] / 'deploy/webos/libexec/mat'
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location('mat_output', HERE / 'receiver.py')
receiver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(receiver)
from carrier import HEADER, checksum


def record(magic, count=0, payload=b''):
    index, pts = (7, 48000) if magic == b'TVMS' else (count, count * 960)
    return HEADER.pack(magic, 1, index, pts, len(payload), checksum(payload) if payload else 0) + payload


class Output:
    def __init__(self):
        self.count = 0
        self.route_written = False
        self.opened = self.drained = False

    def still_owned(self): return True
    def open(self): self.opened = True
    def check_bus(self): pass
    def drain(self): self.drained = True; return True
    def feed(self, data, pts, crc):
        if checksum(data) != crc:
            raise ValueError('CRC differs')
        self.count += 1


class ReceiverTests(unittest.TestCase):
    def test_control_query_stall_does_not_block_audio_feeding(self):
        entered, release = threading.Event(), threading.Event()
        class SlowControl(Output):
            def still_owned(self):
                entered.set()
                release.wait(2)
                return True
        client, output, failures, thread = self.start(SlowControl())
        try:
            client.sendall(record(b'TVMS'))
            self.assertEqual(client.recv(1), b'S')
            self.assertTrue(entered.wait(1))
            time.sleep(.55)  # Cross the old synchronous control-poll interval.
            for count in range(3):
                client.sendall(record(b'TVMT', count, bytes(61440)))
            until = time.monotonic() + .3
            while output.count != 3 and time.monotonic() < until:
                time.sleep(.005)
            self.assertEqual(output.count, 3)
        finally:
            release.set()
        client.sendall(record(b'TVME', 3))
        self.assertEqual(client.recv(1), b'D')
        client.shutdown(socket.SHUT_WR)
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertFalse(failures)

    def test_ownership_loss_is_still_terminal(self):
        class LostOwner(Output):
            def still_owned(self): return False
        client, output, failures, thread = self.start(LostOwner())
        client.sendall(record(b'TVMS'))
        self.assertEqual(client.recv(1), b'S')
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(failures), 1)
        self.assertIn('owner changed', str(failures[0]))

    def test_stalled_control_proof_expires(self):
        entered, release = threading.Event(), threading.Event()
        class StalledControl(Output):
            def still_owned(self):
                entered.set()
                release.wait(4)
                return True
        client, _, failures, thread = self.start(StalledControl())
        try:
            client.sendall(record(b'TVMS'))
            self.assertEqual(client.recv(1), b'S')
            self.assertTrue(entered.wait(1))
            time.sleep(2.2)
        finally:
            release.set()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(failures), 1)
        self.assertIn('verification stalled', str(failures[0]))

    def test_progress_distinguishes_late_arrival_and_local_buffering(self):
        events = []
        output = receiver.Output(None, lambda phase, **values: events.append((phase, values)))
        output.count = 250
        output.first_arrival = 10.0
        output.last_end = 5200000000
        output.running = lambda: 5100000000
        class FakeGst:
            def stats(self, sink): return {'rendered': 244, 'dropped': 0}
            def prop(self, src, name, ctype): return 122880
        output.g = FakeGst()
        with patch.object(receiver.time, 'monotonic', return_value=15.2):
            output.progress()
        phase, values = events[0]
        self.assertEqual(phase, 'output-progress')
        self.assertEqual(values['presentationLeadMs'], 100.0)
        self.assertEqual(values['arrivalAgeMs'], 200.0)
        self.assertEqual(values['queuedBytes'], 122880)
        self.assertEqual(values['stats']['rendered'], 244)

    def pair(self):
        client, server = socket.socketpair()
        client.settimeout(2)
        server.settimeout(2)
        self.addCleanup(client.close)
        self.addCleanup(server.close)
        return client, server

    def start(self, output=None):
        client, server = self.pair()
        output = output or Output()
        failures = []
        def run():
            try:
                receiver.serve(server, output, lambda: True, [False], lambda *_, **__: None)
            except BaseException as e:
                failures.append(e)
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.assertEqual(client.recv(1), b'R')
        return client, output, failures, thread

    def test_fragmented_profile_cycle_and_authenticated_end(self):
        client, output, failures, thread = self.start()
        profile = record(b'TVMS')
        client.sendall(profile[:3]); client.sendall(profile[3:])
        self.assertEqual(client.recv(1), b'S')
        cycle = record(b'TVMT', 0, bytes(61440))
        for i in range(0, len(cycle), 997):
            client.sendall(cycle[i:i+997])
        client.sendall(record(b'TVME', 1))
        self.assertEqual(client.recv(1), b'D')
        client.shutdown(socket.SHUT_WR)
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(output.count, 1)
        self.assertTrue(output.drained)

    def test_abandoned_auto_candidate_never_opens_audio(self):
        client, output, failures, thread = self.start()
        client.shutdown(socket.SHUT_WR)
        thread.join(2)
        self.assertFalse(output.opened)
        self.assertFalse(failures)

    def test_cycle_before_negotiation_is_rejected(self):
        client, _, failures, thread = self.start()
        client.sendall(record(b'TVMT', 0, bytes(61440)))
        thread.join(2)
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], RuntimeError)

    def test_duplicate_profile_and_out_of_order_cycles(self):
        for bad in (record(b'TVMS'), record(b'TVMT', 1, bytes(61440))):
            with self.subTest(bad=bad[:4]):
                client, _, failures, thread = self.start()
                client.sendall(record(b'TVMS'))
                self.assertEqual(client.recv(1), b'S')
                client.sendall(bad[:HEADER.size])
                thread.join(2)
                self.assertEqual(len(failures), 1)

    def test_truncated_cycle_is_rejected(self):
        client, _, failures, thread = self.start()
        client.sendall(record(b'TVMS'))
        self.assertEqual(client.recv(1), b'S')
        client.sendall(record(b'TVMT', 0, bytes(61440))[:100])
        client.shutdown(socket.SHUT_WR)
        thread.join(2)
        self.assertEqual(len(failures), 1)

    def test_preflight_rejects_arc_stereo_and_wrong_output(self):
        sound = dict(soundOutput='external_arc', eArcSupport='on', soundOutputDigital='auto')
        rx = dict(arcActivation='eARC', advancedEarcCapability=[dict(audioCodingType='PCM', maxChannelNumber=8)])
        self.assertTrue(receiver.eligible(sound, rx))
        self.assertFalse(receiver.eligible(dict(sound, soundOutput='tv_speaker'), rx))
        self.assertFalse(receiver.eligible(sound, dict(rx, arcActivation='ARC')))
        self.assertFalse(receiver.eligible(sound, dict(rx, advancedEarcCapability=[])))

    def test_dependency_manifest_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / 'libexec/mat'
            target.mkdir(parents=True)
            raw = json.dumps({n: hashlib.sha256((HERE / n).read_bytes()).hexdigest()
                              for n in ('carrier.py', 'runtime.py', 'native_identity.py')}).encode()
            (target / 'manifest.json').write_bytes(raw)
            for name in ('carrier.py', 'runtime.py', 'native_identity.py'):
                (target / name).write_bytes((HERE / name).read_bytes())
            (target / 'carrier.py').write_text('raise AssertionError("must not execute")')
            with self.assertRaisesRegex(RuntimeError, 'dependency differs'):
                receiver.load_dependencies(root, hashlib.sha256(raw).hexdigest())

    def test_cleanup_continues_after_disconnect_failure(self):
        calls = []
        class TV:
            def connect(self, *args): calls.append('disconnect'); raise RuntimeError('failed')
            def foreground(self): return receiver.APP
            def earc(self, value=None): calls.append('route'); return receiver.TARGET if value is None else value
        output = receiver.Output(TV(), lambda *_, **__: None)
        output.connected = True
        output.resource = type('R', (), dict(port=0, close=lambda _: calls.append('release')))()
        output.native = type('N', (), dict(close=lambda _: calls.append('native-close')))()
        self.assertFalse(output.close())
        self.assertEqual(calls, ['disconnect', 'native-close', 'release'])


if __name__ == '__main__':
    unittest.main()
