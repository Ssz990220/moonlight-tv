"""Linux device-free launch contract: original PID survives, logs stay filtered."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LauncherTest(unittest.TestCase):
    def test_native_pid_and_optional_worker(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary)
            for name in ('bin', 'lib', 'libexec', 'cache'):
                (app / name).mkdir()
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            str(ROOT / 'src/opus71_launcher.c'), '-o', str(app / 'bin/moonlight-opus71')], check=True)
            flags = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'gstreamer-1.0'], text=True).split()
            backend = ROOT / 'third_party/ss4s/modules/webos/ndl/webos5'
            subprocess.run(['cc', '-std=c11', '-shared', '-fPIC', str(backend / 'opus71_route.c'),
                            str(backend / 'opus_config.c'), '-I' + str(backend), *flags, '-lpthread', '-ldl',
                            '-o', str(app / 'lib/libss4s-opus71-route.so')], check=True)
            shutil.copy(ROOT / 'deploy/webos/libexec/opus71_session.py', app / 'libexec')
            stub = app / 'bin/moonlight'
            stub.write_text('''#!/usr/bin/env python3
import os,json,time
from pathlib import Path
root=Path(__file__).resolve().parents[1]
(root/'cache/pid.json').write_text(json.dumps({'nativePid':os.getpid(),'enabled':os.environ.get('SS4S_WEBOS_OPUS71')}))
print('System: webOS 10.3.1',flush=True)
print('Video module: webOS NDL',flush=True)
print('AUTH_TOKEN=must-not-be-persisted',flush=True)
time.sleep(.3)
''')
            stub.chmod(0o755)
            child = subprocess.Popen([str(app / 'bin/moonlight-opus71')])
            self.assertEqual(child.wait(timeout=8), 0)
            evidence = json.loads((app / 'cache/pid.json').read_text())
            self.assertEqual(evidence['nativePid'], child.pid)
            self.assertEqual(evidence['enabled'], '1')
            for _ in range(20):
                record = app / 'cache/opus71-startup.json'
                if record.exists() and 'Video module' in record.read_text():
                    break
                time.sleep(.05)
            text = record.read_text()
            self.assertIn('webOS NDL', text)
            self.assertNotIn('AUTH_TOKEN', text)


if __name__ == '__main__':
    unittest.main()
