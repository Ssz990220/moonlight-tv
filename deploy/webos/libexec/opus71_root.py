#!/usr/bin/env python3
"""Per-application-session root broker; no boot service or system/plugin edits."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import time
import types

APP = 'com.ssz990220.moonlight.opus71'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--worker-sha', required=True)
    args = parser.parse_args()
    if os.geteuid() != 0 or args.pid <= 1:
        return 1
    root = args.root
    allowed = [Path(base) / APP for base in ('/media/developer/apps/usr/palm/applications',
               '/media/cryptofs/apps/usr/palm/applications', '/usr/palm/applications')]
    if root not in allowed:
        return 1
    proc = Path('/proc') / str(args.pid)
    def identity():
        executable = os.readlink(str(proc / 'exe'))
        if not executable.endswith('/' + APP + '/bin/moonlight'):
            return None
        return ((proc / 'stat').read_text().rsplit(')', 1)[1].split()[19], proc.stat().st_uid)
    try:
        original = identity()
    except OSError:
        return 1
    if not original:
        return 1
    data = (root / 'libexec/opus71_session.py').read_bytes()
    if hashlib.sha256(data).hexdigest() != args.worker_sha:
        return 1
    # Execute exactly the bytes that were checked; no import-time path lookup.
    policy = types.ModuleType('opus71_verified_policy')
    exec(compile(data, 'verified-opus71-policy', 'exec'), policy.__dict__)
    def root_luna(uri, payload):
        master, slave = os.openpty()
        try:
            result = subprocess.run(['luna-send', '-n', '1', '-w', '1500', '-f', uri, json.dumps(payload)],
                stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, timeout=3, check=True)
            value = json.loads(result.stdout)
            if isinstance(value, dict) and value.get('returnValue') is False:
                raise RuntimeError('request rejected')
            return value
        finally:
            os.close(slave); os.close(master)
    policy.luna = root_luna
    original_foreground = policy.foreground
    def owned_foreground():
        try:
            if identity() != original:
                return None
        except OSError:
            return None
        return original_foreground()
    # A second instance has the same app ID but a different PID/start time.
    # Never restore or apply the old instance's route to that new owner.
    policy.foreground = owned_foreground
    run = Path('/tmp') / ('moonlight-opus71-root-' + str(args.pid))
    run.mkdir(mode=0o700, exist_ok=True)
    info = run.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        return 1
    lock = (run / 'lock').open('a+')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 0
    stopping = [False]
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda *_: stopping.__setitem__(0, True))
    def status(phase, **values):
        temp = run / 'status.tmp'
        temp.write_text(json.dumps(dict(phase=phase, nativePid=args.pid, **values)))
        temp.replace(run / 'status.json')
    lease = policy.Policy()
    key = None
    proven = False
    started = time.monotonic()
    status('waiting', controlsWritten=False)
    try:
        while not stopping[0] and time.monotonic() - started < 21600:
            try:
                if identity() != original:
                    break
            except OSError:
                break
            try:
                path = root / 'cache/opus71-session.json'
                fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    st = os.fstat(fd)
                    if not stat.S_ISREG(st.st_mode) or st.st_uid != original[1] or st.st_size > 2048:
                        raise ValueError('journal owner or size')
                    event = json.loads(os.read(fd, 2049))
                finally:
                    os.close(fd)
                valid = (event.get('pid') == args.pid and event.get('active') is True and
                         event.get('caps') is True and isinstance(event.get('seq'), int) and
                         isinstance(event.get('since'), (int, float)) and 0 <= event['since'] <= time.monotonic())
                next_key = (event.get('seq'), event.get('since')) if valid else None
                if next_key != key:
                    lease.restore(); key = next_key; proven = False
                if key:
                    log = subprocess.check_output(['dmesg'], stderr=subprocess.DEVNULL,
                                                  universal_newlines=True, timeout=3)
                    # Retain proof over ring-buffer rotation, but revoke any later
                    # real format on this native PID that is not PCM8/acmod21.
                    primary = []
                    import re
                    own = re.compile(r'\(0*' + str(args.pid) + r':\d+\)')
                    for line in log.splitlines():
                        stamp = re.match(r'^\[\s*([0-9.]+)\]', line)
                        if (stamp and float(stamp[1]) >= key[1] and own.search(line) and
                            'lgao_push_first_event' in line and 'BYPASS' not in line):
                            primary.append(line)
                    if primary and not all(re.search(pattern, primary[-1]) for pattern in (
                        r'channels=\(int\)8\D', r'acmod=\(int\)21(?:\D|$)', r'rate=\(int\)48000\D')):
                        proven = False
                    elif not proven:
                        proven = policy.kernel_proven(log, args.pid, key[1])
                    if lease.owned and (not proven or not lease.still_owned()):
                        lease.restore()
                    if proven and not lease.owned:
                        lease.apply()
                elif lease.owned:
                    lease.restore()
                status('lpcm8-requested' if lease.owned else 'waiting', controlsWritten=lease.owned)
            except FileNotFoundError:
                lease.restore(); key = None; proven = False
                status('waiting', controlsWritten=False)
            except Exception as error:
                lease.restore(); key = None; proven = False
                status('unavailable', errorClass=type(error).__name__, controlsWritten=False)
            time.sleep(1)
    finally:
        lease.restore()
        for path in run.iterdir():
            path.unlink()
        run.rmdir()
        lock.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
