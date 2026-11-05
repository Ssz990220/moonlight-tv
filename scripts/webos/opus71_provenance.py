#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[2]
def revision(path):
    return subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()

value = {
    'appId': 'com.ssz990220.moonlight.opus71',
    'version': '1.6.100',
    'moonlightCommit': revision(root),
    'ss4sCommit': revision(root / 'third_party/ss4s'),
    'commonCommit': revision(root / 'core/moonlight-common-c'),
    'tvInstalled': False,
    'tvRuntimeValidated': False,
    'outputGoal': 'Configurable Auto/Opus/Require MAT; live authenticated MAT to native ES/HBR eARC; integrated AV validation pending',
    'artifacts': {},
}
for path in sorted((root / 'dist').glob('*.ipk')):
    value['artifacts'][path.name] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}
(root / 'dist/opus71-build-provenance.json').write_text(json.dumps(value, indent=2) + '\n')
