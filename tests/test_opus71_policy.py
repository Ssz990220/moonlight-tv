import importlib.util
from pathlib import Path
import unittest
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
