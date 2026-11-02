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
            flags = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'gstreamer-1.0'], text=True).split()
            backend = ROOT / 'third_party/ss4s/modules/webos/ndl/webos5'
            subprocess.run(['cc', '-std=c11', '-shared', '-fPIC', str(backend / 'opus71_route.c'),
                            str(backend / 'opus71_load.c'),
                            str(backend / 'opus_config.c'), '-I' + str(backend), *flags, '-lpthread', '-ldl',
                            '-o', str(app / 'lib/libss4s-opus71-route.so')], check=True)
            shutil.copy(ROOT / 'deploy/webos/libexec/opus71_session.py', app / 'libexec')
            stub = app / 'stub.c'
            stub.write_text(r'''#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <time.h>
int opus71_launcher_start(char **argv);
int main(int argc, char **argv) {
 (void)argc;
 if (opus71_launcher_start(argv)) return 1;
 char executable[4096];
 ssize_t n=readlink("/proc/self/exe",executable,sizeof(executable)-1);
 if(n<=0)return 2;
 executable[n]=0;
 FILE *f=fopen("cache/pid.json","w");
 if(!f)return 3;
 const char *enabled=getenv("SS4S_WEBOS_OPUS71");
 fprintf(f,"{\"nativePid\":%ld,\"enabled\":\"%s\",\"executable\":\"%s\"}",
         (long)getpid(), enabled ? enabled : "off", executable);
 fclose(f);
 puts("System: webOS 10.3.1");
 puts("Video module: webOS NDL");
 puts("AUTH_TOKEN=must-not-be-persisted");
 fflush(stdout);
 struct timespec delay={0,300000000};nanosleep(&delay,NULL);
 return 0;
}
''')
            executable = app / 'bin/moonlight'
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            str(ROOT / 'src/opus71_launcher.c'), str(stub), '-o', str(executable)], check=True)
            child = subprocess.Popen([str(executable)], cwd=app)
            self.assertEqual(child.wait(timeout=8), 0)
            evidence = json.loads((app / 'cache/pid.json').read_text())
            self.assertEqual(evidence['nativePid'], child.pid)
            self.assertEqual(evidence['enabled'], '1')
            self.assertEqual(evidence['executable'], str(executable))
            for _ in range(20):
                record = app / 'cache/opus71-startup.json'
                if record.exists() and 'Video module' in record.read_text():
                    break
                time.sleep(.05)
            text = record.read_text()
            self.assertIn('webOS NDL', text)
            self.assertNotIn('AUTH_TOKEN', text)
            # Missing worker still runs the same registered native executable,
            # with experimental eight-channel capability disabled.
            (app / 'libexec/opus71_session.py').unlink()
            child = subprocess.Popen([str(executable)], cwd=app, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
            self.assertEqual(child.wait(timeout=8), 0)
            evidence = json.loads((app / 'cache/pid.json').read_text())
            self.assertEqual(evidence['nativePid'], child.pid)
            self.assertEqual(evidence['executable'], str(executable))
            self.assertEqual(evidence['enabled'], 'off')


if __name__ == '__main__':
    unittest.main()
