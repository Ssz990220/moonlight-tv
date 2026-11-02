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
import threading
import time

APP = 'com.ssz990220.moonlight.opus71'
TARGET = [2, 1, 8, 0, 1]


def capture_startup(stream, root):
    """Retain backend initialization messages only, never connection/media logs."""
    rows = []
    pattern = re.compile(r'(?:Module `[^`]+` (?:can.t be loaded|check result):.*|'
                         r'(?:Video|Audio) module:.*|Video capability: [0-9 x,FPSp]+|'
                         r'Panel native resolution: [0-9 x,:a-z]+|'
                         r'Opus71 decoder input: full eight-channel OpusHead applied|'
                         r'Opus configuration: [0-9 a-z,]+|'
                         r'System:.*|Root route bridge:.*)')
    def lines():
        while True:
            try:
                line = stream.readline()
            except OSError:  # A PTY returns EIO after its child closes.
                return
            if not line:
                return
            yield line
    for line in lines():
        match = pattern.search(line)
        if not match or len(rows) >= 24:
            continue
        message = re.sub(r'https?://\S+', '[URL]', match[0])
        message = re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', '[IP]', message)
        rows.append(message[:1000])
        try:
            folder = root / 'cache'
            folder.mkdir(exist_ok=True)
            (folder / 'opus71-startup.json').write_text(json.dumps({'backendInitialization': rows}, indent=2))
        except OSError:
            pass


def luna(uri, payload):
    result = subprocess.run(['luna-send', '-n', '1', '-w', '1500', '-f', uri,
                             json.dumps(payload)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, universal_newlines=True,
                            timeout=3, check=True)
    value = json.loads(result.stdout)
    if isinstance(value, dict) and value.get('returnValue') is False:
        raise RuntimeError('request rejected')
    return value


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


def worker(root, parent_pid, read_fd, ready_fd, log_fd):
    root = Path(root).resolve()
    # Drop inherited LS2 / application-launch handles. Keep only owned pipes.
    keep = {read_fd, ready_fd, log_fd}
    for entry in Path('/proc/self/fd').iterdir():
        fd = int(entry.name)
        if fd > 2 and fd not in keep:
            try:
                os.close(fd)
            except OSError:
                pass
    output = os.fdopen(log_fd, 'r', errors='replace')
    threading.Thread(target=capture_startup, args=(output, root), daemon=True).start()
    stopping = [False]
    def stop(_signum, _frame):
        stopping[0] = True
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, stop)
    pending = b''
    journal = {'pid': parent_pid, 'active': False, 'caps': False, 'inputCaps': False, 'seq': 0, 'since': 0}
    def publish():
        try:
            folder = root / 'cache'
            folder.mkdir(exist_ok=True)
            temp = folder / 'opus71-session.tmp'
            temp.write_text(json.dumps(journal))
            temp.replace(folder / 'opus71-session.json')
        except OSError:
            pass
    publish()
    os.write(ready_fd, b'1')
    os.close(ready_fd)
    try:
        while not stopping[0]:
            try:
                os.kill(parent_pid, 0)
            except ProcessLookupError:
                break
            ready, _, _ = select.select([read_fd], [], [], .25)
            if ready:
                data = os.read(read_fd, 4096)
                if not data:
                    break
                pending += data
                while b'\n' in pending:
                    row, pending = pending.split(b'\n', 1)
                    match = re.fullmatch(rb'([BEFRI]) (\d+) (\d+)', row)
                    if not match:
                        continue
                    kind, seq, stamp = match[1], int(match[2]), int(match[3]) / 1000.0
                    if kind == b'B':
                        journal.update(active=True, caps=False, inputCaps=False, seq=seq, since=stamp)
                        publish()
                    elif seq == journal['seq']:
                        if kind == b'I':
                            journal['inputCaps'] = True
                        elif kind == b'F':
                            journal['caps'] = True
                        else:
                            journal.update(active=False, caps=False)
                        publish()
    finally:
        journal.update(active=False, caps=False)
        publish()
        os.close(read_fd)
    return 0


if __name__ == '__main__':
    if len(sys.argv) != 7 or sys.argv[1] != '--worker':
        raise SystemExit('Launch through the native application entry point')
    sys.exit(worker(sys.argv[2], *map(int, sys.argv[3:])))
