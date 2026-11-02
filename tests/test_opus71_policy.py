import importlib.util
from pathlib import Path
import unittest
import json
import os
import select
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / 'deploy/webos/libexec/opus71_session.py'
spec = importlib.util.spec_from_file_location('policy', path)
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)

SOUND = dict(soundOutput='external_arc', soundOutputDigital='auto', eArcSupport='on')
RX = dict(arcActivation='eARC', advancedEarcCapability=[dict(audioCodingType='PCM', maxChannelNumber=8)])


def log(pid=123, acmod=21, start=10):
    fields = 'channels=(int)8, rate=(int)48000, acmod=(int)' + str(acmod)
    return ('[ %s] (00123:124) lgao_push_first_event %s\n' % (start, fields)).replace('00123:', str(pid) + ':') + \
           '[ %s] (1:2) Pcmcvt_Event.1332 %s\n' % (start + .1, fields)


class PolicyTest(unittest.TestCase):
    @unittest.skipUnless(Path('/proc/self/fd').exists(), 'Linux worker FD lifecycle')
    def test_live_format_can_recover_after_initial_six_channel_caps(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            event_r, event_w = os.pipe()
            ready_r, ready_w = os.pipe()
            log_r, log_w = os.pipe()
            child = subprocess.Popen([sys.executable, '-B', str(path), '--worker',
                str(root), str(os.getpid()), str(event_r), str(ready_w), str(log_r)],
                pass_fds=(event_r, ready_w, log_r))
            for fd in (event_r, ready_w, log_r): os.close(fd)
            def send(text, expected):
                os.write(event_w, text.encode())
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    try: value = json.loads((root / 'cache/opus71-session.json').read_text())
                    except (FileNotFoundError, json.JSONDecodeError): value = {}
                    if all(value.get(k) == v for k, v in expected.items()): return
                    time.sleep(.01)
                self.fail('worker did not publish expected state: ' + str(expected))
            try:
                self.assertTrue(select.select([ready_r], [], [], 3)[0])
                self.assertEqual(os.read(ready_r, 1), b'1')
                send('B 1 1000\n', dict(active=True, caps=False))
                send('L 1 1001\nI 1 1002\n', dict(loadConfig=True, inputCaps=True))
                send('R 1 1003\n', dict(active=True, caps=False))
                send('F 1 1004\n', dict(active=True, caps=True))
                send('R 1 1005\n', dict(active=True, caps=False))
                send('E 1 1006\n', dict(active=False, caps=False))
            finally:
                os.close(event_w); os.close(ready_r); os.close(log_w)
                try: child.wait(timeout=3)
                except subprocess.TimeoutExpired: child.kill(); child.wait()

    def test_eligibility(self):
        self.assertTrue(p.eligible(SOUND, RX))
        for key, value in [('soundOutput', 'tv_speaker'), ('soundOutputDigital', 'passThrough'), ('eArcSupport', 'off')]:
            self.assertFalse(p.eligible(dict(SOUND, **{key: value}), RX))
        self.assertFalse(p.eligible(SOUND, dict(RX, arcActivation='ARC')))
        self.assertFalse(p.eligible(SOUND, dict(RX, advancedEarcCapability=[])))

    def test_proof_requires_real71_and_owner(self):
        self.assertTrue(p.kernel_proven(log(), 123, 9))
        self.assertFalse(p.kernel_proven(log(acmod=7), 123, 9))
        self.assertFalse(p.kernel_proven(log(), 999, 9))
        self.assertFalse(p.kernel_proven(log(), 123, 11))
        self.assertFalse(p.kernel_proven(log().replace('rate=(int)48000', 'rate=(int)44100'), 123, 9))
        self.assertFalse(p.kernel_proven(log().replace('lgao_push_first_event', 'lgao_push_first_event BYPASS'), 123, 9))
        self.assertFalse(p.kernel_proven(log() + '[ 11] (123:124) lgao_push_first_event channels=(int)2, rate=(int)48000, acmod=(int)2', 123, 9))

    def test_apply_and_restore(self):
        before = [2, 7, 0, 0, 1]
        control = before[:]
        writes = []
        def earc(value=None):
            if value is not None:
                writes.append(value[:])
                control[:] = value
            return control[:]
        with patch.object(p, 'foreground', return_value=p.APP), patch.object(p, 'settings', return_value=SOUND), \
             patch.object(p, 'receiver', return_value=RX), patch.object(p, 'earc', side_effect=earc):
            session = p.Policy()
            self.assertTrue(session.apply())
            session.restore()
            session.restore()
        self.assertEqual(writes, [p.TARGET, before])

    def test_no_restore_over_user_or_app_change(self):
        for app, sound, control in [('other', SOUND, p.TARGET), (p.APP, dict(SOUND, soundOutput='tv_speaker'), p.TARGET),
                                    (p.APP, SOUND, [2, 7, 0, 0, 1])]:
            session = p.Policy()
            session.owned = True
            session.previous = [2, 7, 0, 0, 1]
            session.sound = SOUND
            with patch.object(p, 'foreground', return_value=app), patch.object(p, 'settings', return_value=sound), \
                 patch.object(p, 'earc', return_value=control) as mixer:
                session.restore()
                self.assertFalse(any(call.args for call in mixer.call_args_list))

    def test_ineligible_has_no_writes(self):
        with patch.object(p, 'foreground', return_value=p.APP), patch.object(p, 'settings', return_value=dict(SOUND, soundOutputDigital='passThrough')), \
             patch.object(p, 'receiver', return_value=RX), patch.object(p, 'earc') as mixer:
            self.assertFalse(p.Policy().apply())
            mixer.assert_not_called()

    def test_permission_failure_leaves_app_alive(self):
        session = p.Policy()
        session.owned = True
        with patch.object(p, 'foreground', side_effect=PermissionError):
            session.restore()
        self.assertFalse(session.owned)


if __name__ == '__main__':
    unittest.main()
