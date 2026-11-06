#!/usr/bin/env python3
"""Reject streaming packages containing Debug's synthetic FEC self-test."""
import io
import json
from pathlib import Path
import subprocess
import tarfile

root = Path(__file__).resolve().parents[2]
cache = root / 'build/webos-easy_build/CMakeCache.txt'
if 'CMAKE_BUILD_TYPE:STRING=Release' not in cache.read_text().splitlines():
    raise SystemExit('Expected Release build cache')
packages = list((root / 'dist').glob('*.ipk'))
if len(packages) != 1:
    raise SystemExit('Expected exactly one application package')
payload = subprocess.check_output(['ar', 'p', str(packages[0]), 'data.tar.gz'])
with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as archive:
    entries = [entry for entry in archive.getmembers() if entry.isfile() and
               entry.name.removeprefix('./') ==
               'usr/palm/applications/com.ssz990220.moonlight.opus71/bin/moonlight']
    if len(entries) != 1:
        raise SystemExit('Expected native Moonlight entry point')
    binary = archive.extractfile(entries[0]).read()
if not binary.startswith(b'\x7fELF'):
    raise SystemExit('Entry point is not ELF')
if b'Recovery error at %d: expected' in binary:
    raise SystemExit('Debug-only FEC validation is present')
print(json.dumps({'buildType': 'Release', 'debugFecSelfTestAbsent': True}))
