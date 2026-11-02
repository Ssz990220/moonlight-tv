#!/usr/bin/env python3
"""App-owned, temporary C5 LPCM8 policy. No persistent TV or plugin writes.

The child emits only session generations and monotonic timestamps on a pipe.
Require the current child's native Opus PCM8/acmod21 caps, fresh matching
kernel first-format and converter evidence, Auto/eARC, and PCM8 receiver caps.
Permission failures leave the route unchanged. Never log service responses.
"""
import json
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import sys
import time

APP = 'com.ssz990220.moonlight.opus71'
TARGET = [2, 1, 8, 0, 1]


def luna(uri, payload):
    master, slave = os.openpty()
    try:
        result = subprocess.run(['luna-send', '-n', '1', '-w', '1500', '-f', uri,
                                 json.dumps(payload)], stdin=slave, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, universal_newlines=True,
                                timeout=3, check=True)
        value = json.loads(result.stdout)
        if isinstance(value, dict) and value.get('returnValue') is False:
            raise RuntimeError('request rejected')
        return value
    finally:
        os.close(slave)
        os.close(master)


def foreground():
    return luna('luna://com.webos.applicationManager/getForegroundAppInfo', {}).get('appId')


def settings():
    return luna('luna://com.webos.settingsservice/getSystemSettings', {
        'category': 'sound', 'keys': ['soundOutput', 'soundOutputDigital', 'eArcSupport']})['settings']


def receiver():
    value = luna('luna://com.webos.service.audiooutput/quality/getSettings', {
        'category': 'external_arc', 'settings': {}})
    return next(x['value'] for x in value['settings'] if x['category'] == 'external_arc')


def eligible(sound, rx):
    return (sound.get('soundOutput') == 'external_arc' and
            sound.get('soundOutputDigital') == 'auto' and sound.get('eArcSupport') == 'on' and
            rx.get('arcActivation') == 'eARC' and any(
                isinstance(x, dict) and x.get('audioCodingType') == 'PCM' and
                isinstance(x.get('maxChannelNumber'), int) and x['maxChannelNumber'] >= 8
                for x in rx.get('advancedEarcCapability', [])))


def earc(value=None):
    args = ['amixer', '-c', '0', 'cget' if value is None else 'cset',
            'name=Sndout EARC Outputtype']
    if value is not None:
        args.append(','.join(map(str, value)))
    output = subprocess.check_output(args, stderr=subprocess.DEVNULL,
                                     universal_newlines=True, timeout=3)
    match = re.search(r'^\s*: values=([0-9,]+)\s*$', output, re.M)
    if not match:
        raise RuntimeError('control unavailable')
    values = [int(x) for x in match[1].split(',')]
    if len(values) != 5:
        raise RuntimeError('control geometry')
    return values


def kernel_proven(log, pid, since):
    primary, converter = None, None
    own = re.compile(r'\(0*' + str(pid) + r':\d+\)')
    for line in log.splitlines():
        stamp = re.match(r'^\[\s*([0-9.]+)\]', line)
        if not stamp or float(stamp[1]) < since:
            continue
        fields = {}
        for key in ('channels', 'acmod', 'rate'):
            value = re.search(r'\b' + key + r'=\(int\)(\d+)(?:\D|$)', line)
            if value:
                fields[key] = int(value[1])
        t = float(stamp[1])
        if own.search(line) and 'lgao_push_first_event' in line and 'BYPASS' not in line and fields:
            primary = (t, fields)
        if 'Pcmcvt_Event' in line and fields:
            converter = (t, fields)
    expected = {'channels': 8, 'acmod': 21, 'rate': 48000}
    return bool(primary and converter and primary[1] == expected and converter[1] == expected and
                -.05 <= converter[0] - primary[0] <= 5)


class Policy:
    def __init__(self):
        self.previous = None
        self.sound = None
        self.owned = False

    def apply(self):
        sound = settings()
        if foreground() != APP or not eligible(sound, receiver()):
            return False
        previous = earc()
        # This check is repeated just before the sole write.
        if foreground() != APP or settings() != sound:
            return False
        self.previous, self.sound = previous, sound
        self.owned = True  # An uncertain write must still enter cleanup.
        if earc(TARGET) != TARGET:
            self.restore()
            raise RuntimeError('LPCM8 request rejected')
        print('Moonlight Opus71: temporary LPCM8 requested; receiver confirmation required.', file=sys.stderr)
        return True

    def still_owned(self):
        return (foreground() == APP and settings() == self.sound and earc() == TARGET)

    def restore(self):
        if not self.owned:
            return
        try:
            if self.still_owned():
                earc(self.previous)
        except Exception as error:
            print('Moonlight Opus71: restore unavailable (' + type(error).__name__ + ').', file=sys.stderr)
        finally:
            self.owned = False


def main(root):
    root = Path(root).resolve()
    read_fd, write_fd = os.pipe()
    os.set_blocking(write_fd, False)
    env = dict(os.environ, APPID=APP, SS4S_WEBOS_OPUS71='1',
               SS4S_OPUS71_NOTIFY_FD=str(write_fd))
    # Preload only this child's app-local library. Do not inherit another preload.
    env['LD_PRELOAD'] = str(root / 'lib/libss4s-opus71-route.so')
    child = subprocess.Popen([str(root / 'bin/moonlight')] + sys.argv[2:],
                             env=env, pass_fds=(write_fd,))
    os.close(write_fd)
    stopping = [False]
    def stop(signum, _frame):
        stopping[0] = True
        if child.poll() is None:
            child.send_signal(signum)
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, stop)
    policy = Policy()
    session = None
    pending = b''
    last_check = 0
    try:
        while child.poll() is None and not stopping[0]:
            ready, _, _ = select.select([read_fd], [], [], .25)
            if ready:
                pending += os.read(read_fd, 4096)
                while b'\n' in pending:
                    row, pending = pending.split(b'\n', 1)
                    match = re.fullmatch(rb'([BEFR]) (\d+) (\d+)', row)
                    if not match:
                        continue
                    kind, seq, stamp = match[1], int(match[2]), int(match[3]) / 1000.0
                    if kind == b'B':
                        policy.restore()
                        session = {'seq': seq, 'since': stamp, 'caps': False, 'applied': False,
                                   'deadline': time.monotonic() + 20}
                    elif session and seq == session['seq']:
                        if kind == b'F':
                            session['caps'] = True
                        elif kind in (b'E', b'R'):
                            policy.restore()
                            session = None
            now = time.monotonic()
            if now - last_check < 1:
                continue
            last_check = now
            try:
                if policy.owned and not policy.still_owned():
                    # An app/output/user transition ends our lease. Do not fight it.
                    policy.owned = False
                    session = None
                if session and session['caps'] and not session['applied'] and now < session['deadline']:
                    log = subprocess.check_output(['dmesg'], stderr=subprocess.DEVNULL,
                                                  universal_newlines=True, timeout=3)
                    if kernel_proven(log, child.pid, session['since']):
                        session['applied'] = policy.apply()
            except Exception as error:
                # Service responses and exception text may contain private data.
                print('Moonlight Opus71: route unavailable (' + type(error).__name__ + ').', file=sys.stderr)
                policy.restore()
                session = None
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        try:
            policy.restore()
        finally:
            os.close(read_fd)
    return child.returncode


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
