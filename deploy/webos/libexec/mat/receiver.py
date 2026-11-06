"""App-session MAT ES output on the audited C5 ABI. No installation or hooks.

Only the registered Moonlight PID may supply already authenticated MAT cycles.
The native helper reserves its own ADEC, never substitutes a PCM channel label,
and restores its own eARC lease when that session ends.
"""
import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import re
import select
import signal
import socket
import stat
import struct
import sys
import tempfile
import threading
import time
import types

APP = 'com.ssz990220.moonlight.opus71'
TARGET = [2, 6, 8, 0, 0]
ABI = {
    '/usr/lib/gstreamer-1.0/libgstlgaudiodec.so': '84db367e1ea3eeb4b589bf63910140cfd43ea77f2db124ae6882fbee8ebb6bb7',
    '/usr/lib/gstreamer-1.0/libgstlgaudiosink.so': '90dba3ef32704ce4096bf1e6045d2879d0c2192d507bc04d1e8e98437f420a43',
}


def identity(pid):
    proc = Path('/proc') / str(pid)
    if not os.readlink(str(proc / 'exe')).endswith('/' + APP + '/bin/moonlight'):
        raise RuntimeError('parent executable differs')
    return proc.stat().st_uid, (proc / 'stat').read_text().rsplit(')', 1)[1].split()[19]


def socket_owned(path, uid):
    if not re.fullmatch(r'/tmp/moonlight-mat-[A-Za-z0-9]{6}/audio', str(path)):
        return False
    folder, endpoint = path.parent.lstat(), path.lstat()
    return (stat.S_ISDIR(folder.st_mode) and folder.st_uid == uid and
            stat.S_IMODE(folder.st_mode) == 0o700 and
            stat.S_ISSOCK(endpoint.st_mode) and endpoint.st_uid == uid)


def load_dependencies(root, manifest_sha):
    here = root / 'libexec/mat'
    raw = (here / 'manifest.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest_sha:
        raise RuntimeError('dependency manifest differs')
    manifest = json.loads(raw)
    names = ('carrier', 'runtime', 'native_identity')
    if set(manifest) != {n + '.py' for n in names}:
        raise RuntimeError('unexpected dependency manifest')
    # Execute the exact checked bytes, with no untrusted Python import path.
    for name in names:
        file = here / (name + '.py')
        data = file.read_bytes()
        if hashlib.sha256(data).hexdigest() != manifest[file.name]:
            raise RuntimeError('dependency differs')
        module = types.ModuleType(name)
        module.__file__ = str(file)
        sys.modules[name] = module
        exec(compile(data, str(file), 'exec'), module.__dict__)


def eligible(sound, receiver):
    return (sound.get('soundOutput') == 'external_arc' and
            sound.get('eArcSupport') == 'on' and
            sound.get('soundOutputDigital') in ('auto', 'pass_through') and
            receiver.get('arcActivation') == 'eARC' and any(
                isinstance(x, dict) and x.get('audioCodingType') == 'PCM' and
                isinstance(x.get('maxChannelNumber'), int) and x['maxChannelNumber'] >= 8
                for x in receiver.get('advancedEarcCapability', [])))


class Output:
    def __init__(self, tv, report):
        self.tv, self.report = tv, report
        self.resource = self.g = self.native = None
        self.pipeline = self.src = self.sink = self.bus = self.segment = None
        self.connected = self.route_written = False
        self.route_confirmed = False
        self.previous = None
        self.sound = None
        self.count = 0
        self.input_digest = hashlib.sha256()
        self.origin = self.last_end = None
        self.first_arrival = None
        self.control_check_ms = self.max_control_check_ms = 0
        self.prepare_us = self.push_us = self.max_prepare_us = self.max_push_us = 0
        self.pipeline_timing = {}

    def sample_pipeline_timing(self):
        """Software declarations/clocks only, sampled off the feeder thread."""
        from runtime import P, U, bind
        g = self.g
        if not g or not self.pipeline or not self.sink:
            return
        if not hasattr(self, '_sink_latency'):
            self._sink_latency = bind(C.CDLL('libgstbase-1.0.so.0'),
                                      'gst_base_sink_get_latency', [P], U)
            self._pipeline_latency = bind(g.g, 'gst_pipeline_get_latency', [P], U)
        fields = [('renderDelayNs', 'render-delay', U),
                  ('processingDeadlineNs', 'processing-deadline', U),
                  ('timestampOffsetNs', 'ts-offset', C.c_int64),
                  ('sync', 'sync', C.c_int), ('lipsync', 'lipsync', C.c_int)]
        timing = {key: g.prop(self.sink, name, ctype) for key, name, ctype in fields}
        timing.update(sinkLatencyNs=int(self._sink_latency(self.sink)),
                      pipelineLatencyNs=int(self._pipeline_latency(self.pipeline)),
                      sourceIsLive=g.prop(self.src, 'is-live', C.c_int),
                      pipelineBaseNs=int(g.gst_element_get_base_time(self.pipeline)),
                      sinkBaseNs=int(g.gst_element_get_base_time(self.sink)),
                      runningNs=self.running(), lastBufferEndNs=self.last_end,
                      sampledMonotonicNs=time.monotonic_ns())
        self.pipeline_timing = timing

    def settings(self):
        return self.tv.luna('luna://com.webos.settingsservice/getSystemSettings', {
            'category': 'sound', 'keys': ['soundOutput', 'soundOutputDigital', 'eArcSupport']})['settings']

    def preflight(self):
        if C.sizeof(C.c_void_p) != 4:
            raise RuntimeError('unsupported native audio pointer ABI')
        for path, expected in ABI.items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
                raise RuntimeError('unsupported native audio ABI')
        sound = self.settings()
        value = self.tv.luna('luna://com.webos.service.audiooutput/quality/getSettings', {
            'category': 'external_arc', 'settings': {}})
        receiver = next(x['value'] for x in value['settings'] if x['category'] == 'external_arc')
        if self.tv.foreground() != APP or not eligible(sound, receiver):
            raise RuntimeError('MAT requires foreground app and HDMI eARC capability')
        self.sound = sound

    def still_owned(self):
        return self.tv.foreground() == APP and self.settings() == self.sound

    def open(self):
        from runtime import Resource, Gst, P, bind
        from native_identity import NativeIdentity
        self.preflight()
        rows = self.tv.luna('luna://com.webos.media/getActivePipelines', {})
        # HDMI may retain its independent background TV resource. Do not stop it
        # or borrow its port; RM must grant a separate audio decoder to us.
        if any(any(x.get('resource') == 'ADEC' for x in p.get('resource', [])) and not (
                p.get('type') == 'tv' and {'HDMI_INPUT', 'AHDMIRX'}.issubset(
                    {x.get('resource') for x in p.get('resource', [])})) for p in rows):
            raise RuntimeError('another audio decoder is active')
        self.previous = self.tv.earc()
        self.resource, self.g = Resource(), Gst()
        g, port = self.g, self.resource.port
        self.native = NativeIdentity(g.g, port, 5, lambda **_: None, channels=8)
        caps = ('audio/x-raw,format=(string)S16LE,layout=(string)interleaved,rate=(int)48000,channels=(int)8,'
                'channel-mask=(bitmask)0xc3f,codec=(uint)21,codec-str=(string)mat,acmod=(uint)21,out-channels=(int)8,'
                'es=(boolean)true,data-channels=(int)8,data-bps=(int)16,data-rate=(int)192000,'
                'clock-x4=(boolean)false,atmos=(boolean)true')
        desc = ('appsrc name=audio format=time handle-segment-change=true block=false max-bytes=2457600 caps="' + caps + '" ! '
                'audiosink name=ar index=' + str(port) + ' resource-info="resource, audio-port=(int)' + str(port) +
                ', mixer-port=(int)-1" app-type=webos pcm-bypass=false pcm-multi-ch=false '
                'sync=true lipsync=false async=false audio-only=true')
        error = P()
        self.pipeline = g.gst_parse_launch(desc.encode(), C.byref(error))
        if not self.pipeline or error.value:
            raise RuntimeError('MAT output pipeline rejected')
        self.src = g.gst_bin_get_by_name(self.pipeline, b'audio')
        self.sink = g.gst_bin_get_by_name(self.pipeline, b'ar')
        self.bus = g.gst_element_get_bus(self.pipeline)
        self.segment = g.segment(0)
        clock = bind(g.g, 'gst_system_clock_obtain', [], P)()
        bind(g.g, 'gst_pipeline_use_clock', [P, P], None)(self.pipeline, clock)
        g.gst_object_unref(clock)
        if not g.gst_element_set_state(self.pipeline, 4):
            raise RuntimeError('MAT output start rejected')
        self.tv.connect(port)
        self.connected = True

    def running(self):
        g = self.g
        clock = g.gst_element_get_clock(self.pipeline)
        if not clock:
            raise RuntimeError('MAT output clock unavailable')
        try:
            return int(g.gst_clock_get_time(clock) - g.gst_element_get_base_time(self.pipeline))
        finally:
            g.gst_object_unref(clock)

    def feed(self, payload, pts, crc):
        from carrier import to_lg_carrier
        from runtime import P, U, bind
        g = self.g
        began = time.monotonic_ns()
        encoded = to_lg_carrier(payload, crc)
        self.input_digest.update(payload)
        if self.origin is None:
            self.first_arrival = time.monotonic()
            self.origin = self.running() + 80000000
        stamp = self.origin + pts * 1000000000 // 48000
        # Format discovery needs only a complete carrier. The decoded PCM is
        # deliberately not consumed; a larger game bed can fill that unused
        # native buffer if eight full carriers are fed during startup.
        if self.count < 2:
            self.native.feed(encoded, stamp)
        if g.prop(self.sink, 'pcm-bypass', C.c_int) or g.prop(self.sink, 'pcm-multi-ch', C.c_int):
            raise RuntimeError('MAT PCM processing mode changed')
        if g.prop(self.src, 'current-level-bytes', U) > 1228800:
            raise RuntimeError('MAT native queue limit exceeded')
        prepared = time.monotonic_ns()
        g.push(self.src, encoded, stamp, 20000000, self.segment, 0x200000)
        done = time.monotonic_ns()
        prepare_us, push_us = (prepared - began) // 1000, (done - prepared) // 1000
        self.prepare_us += prepare_us
        self.push_us += push_us
        self.max_prepare_us = max(self.max_prepare_us, prepare_us)
        self.max_push_us = max(self.max_push_us, push_us)
        self.last_end = stamp + 20000000
        self.count += 1
        if self.count % 250 == 0:
            self.progress()
        if self.count >= 75 and not self.route_written:
            words = self.native.snapshot()['decodedInfoWords']
            if words[1] == 5 and words[2] == 48000 and 1 <= words[4] <= 32:
                if not self.still_owned():
                    raise RuntimeError('MAT output lease lost')
                # An uncertain control write must still enter cleanup.
                self.route_written = True
                if self.tv.earc(TARGET) != TARGET:
                    raise RuntimeError('MAT output readback differs')
                ao = P.from_address(self.sink + 0x200).value
                if not ao:
                    raise RuntimeError('MAT output context unavailable')
                bind(C.CDLL('/usr/lib/gstreamer-1.0/libgstlgaudiosink.so'),
                     'lgao_push_first_event', [P], C.c_int)(ao)
                self.route_confirmed = True
                self.report('output-active', nativeFormat=words[1], cycles=self.count)
            elif self.count > 250:
                raise RuntimeError('MAT native format discovery failed')

    def progress(self):
        from runtime import U
        # Numeric timing evidence only. This measures the app pipeline, not
        # Sonos acoustic latency or the native encoder's media PTS mapping.
        now = self.running()
        self.report('output-progress', cycles=self.count, stats=self.g.stats(self.sink),
                    queuedBytes=self.g.prop(self.src, 'current-level-bytes', U),
                    presentationLeadMs=round((self.last_end - now) / 1000000, 3),
                    arrivalAgeMs=round((time.monotonic() - self.first_arrival) * 1000 - self.count * 20, 3),
                    controlCheckMs=self.control_check_ms, maxControlCheckMs=self.max_control_check_ms,
                    feedTiming={'calls': self.count,
                                'prepareMeanUs': self.prepare_us // self.count,
                                'prepareMaxUs': self.max_prepare_us,
                                'pushMeanUs': self.push_us // self.count,
                                'pushMaxUs': self.max_push_us},
                    pipelineTiming=dict(self.pipeline_timing))

    def check_bus(self):
        message = self.g.gst_bus_timed_pop_filtered(self.bus, 0, 2)
        if message:
            self.g.gst_mini_object_unref(message)
            raise RuntimeError('MAT native pipeline error')

    def drain(self):
        from runtime import U
        g = self.g
        if not self.count or g.gst_app_src_end_of_stream(self.src):
            return False
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            self.check_bus()
            stats = g.stats(self.sink)
            if (stats.get('rendered', 0) >= self.count and stats.get('dropped') == 0 and
                    not g.prop(self.src, 'current-level-bytes', U) and self.running() >= self.last_end + 100000000):
                self.report('drained', cycles=self.count, stats=stats)
                return True
            time.sleep(.02)
        return False

    def close(self):
        errors = []
        def attempt(name, call):
            try:
                call()
            except BaseException:
                errors.append(name)
        if self.g and self.sink:
            attempt('final-stats', lambda: self.report('stopping', cycles=self.count,
                    stats=self.g.stats(self.sink), inputSha256=self.input_digest.hexdigest()))
        if self.pipeline:
            attempt('pipeline-stop', lambda: self.g.gst_element_set_state(self.pipeline, 1))
        if self.connected:
            attempt('audio-disconnect', lambda: self.tv.connect(self.resource.port, False))
        if self.native:
            attempt('native-close', self.native.close)
        if self.route_written:
            def restore():
                if self.still_owned() and self.tv.earc() == TARGET:
                    self.tv.earc(self.previous)
                    if self.tv.earc() != self.previous:
                        raise RuntimeError('MAT restore readback differs')
            attempt('route-restore', restore)
        if self.g:
            for obj in (self.src, self.sink, self.bus, self.pipeline):
                if obj:
                    attempt('unref', lambda obj=obj: self.g.gst_object_unref(obj))
            if self.segment:
                attempt('segment-free', lambda: self.g.gst_segment_free(self.segment))
        if self.resource:
            attempt('resource-release', self.resource.close)
        self.report('closed', cycles=self.count, cleanupErrors=errors)
        return not errors


class OwnershipWatch:
    """Poll control services away from the audio feeder; stale proof still fails."""
    def __init__(self, output, alive):
        self.output, self.alive = output, alive
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.verified = time.monotonic()
        self.failure = None
        self.thread = None

    def start(self):
        # Output.open just completed the synchronous ownership preflight.
        self.verified = time.monotonic()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        last_sample = None
        while not self.stop.is_set():
            began = time.monotonic()
            try:
                owned = self.alive() and self.output.still_owned()
                if owned and getattr(self.output, 'route_confirmed', self.output.route_written):
                    owned = self.output.tv.earc() == TARGET
                failure = None if owned else 'MAT session owner changed'
            except Exception:
                failure = 'MAT ownership verification unavailable'
            self.output.control_check_ms = round((time.monotonic() - began) * 1000, 3)
            self.output.max_control_check_ms = max(getattr(self.output, 'max_control_check_ms', 0),
                                                   self.output.control_check_ms)
            with self.lock:
                self.failure = failure
                self.verified = time.monotonic()
            if not failure and hasattr(self.output, 'sample_pipeline_timing') and (last_sample is None or time.monotonic() - last_sample >= 5):
                try:
                    self.output.sample_pipeline_timing()
                except Exception:
                    # Missing diagnostics must never alter media/ownership state.
                    self.output.pipeline_timing = {'unavailable': 1}
                last_sample = time.monotonic()
            if failure or self.stop.wait(.5):
                return

    def check(self):
        if self.thread is None:
            return
        with self.lock:
            failure, verified = self.failure, self.verified
        if failure:
            raise RuntimeError(failure)
        if time.monotonic() - verified > 2:
            raise RuntimeError('MAT ownership verification stalled')

    def close(self):
        self.stop.set()
        if self.thread:
            # Finish read-only control requests before the caller closes its
            # PTY and native resources. Each existing request is bounded.
            self.thread.join(12)


def serve(channel, output, alive, stopped, report):
    watch = OwnershipWatch(output, alive)
    try:
        return serve_audio(channel, output, alive, stopped, report, watch)
    finally:
        watch.close()


def serve_audio(channel, output, alive, stopped, report, watch):
    from carrier import HEADER, validate_header
    channel.sendall(b'R')
    pending = bytearray()
    profiled = ended = False
    last_data = last_alive = time.monotonic()
    begin = last_data
    while not stopped[0] and time.monotonic() - begin < 21600:
        now = time.monotonic()
        watch.check()
        if now - last_alive >= .5:
            if not alive():
                raise RuntimeError('MAT session owner changed')
            last_alive = now
        if now - last_data > (3 if profiled else 130):
            raise RuntimeError('MAT source idle deadline exceeded')
        if select.select([channel], [], [], .03)[0]:
            data = channel.recv(65536)
            if not data:
                if pending:
                    raise RuntimeError('truncated MAT local stream')
                return
            if ended:
                raise RuntimeError('MAT data after authenticated end')
            pending.extend(data)
            last_data = now
        if len(pending) > 2 * 61472:
            raise RuntimeError('MAT local queue limit exceeded')
        while len(pending) >= HEADER.size:
            magic, index, pts, length, crc = validate_header(pending[:HEADER.size], output.count)
            if len(pending) < HEADER.size + length:
                break
            payload = bytes(pending[HEADER.size:HEADER.size + length])
            del pending[:HEADER.size + length]
            if magic == b'TVMS':
                if profiled or output.count:
                    raise RuntimeError('duplicate MAT profile')
                output.open()
                watch.start()
                profiled = True
                channel.sendall(b'S')
                report('receiving', codec=7)
            elif magic == b'TVMT':
                if not profiled or ended:
                    raise RuntimeError('MAT cycle outside profile')
                output.feed(payload, pts, crc)
            else:
                if not profiled or ended or not output.drain():
                    raise RuntimeError('MAT end or drain invalid')
                ended = True
                channel.sendall(b'D')
                if pending:
                    raise RuntimeError('MAT bytes after end')
        if profiled:
            output.check_bus()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--socket', type=Path, required=True)
    parser.add_argument('--manifest-sha', required=True)
    args = parser.parse_args()
    if os.geteuid() != 0 or args.pid <= 1 or args.root not in [Path(base) / APP for base in (
            '/media/developer/apps/usr/palm/applications', '/media/cryptofs/apps/usr/palm/applications',
            '/usr/palm/applications')]:
        return 1
    original = identity(args.pid)
    if not socket_owned(args.socket, original[0]):
        return 1
    load_dependencies(args.root, args.manifest_sha)
    run = Path(tempfile.mkdtemp(prefix='moonlight-mat-root-'))
    # Use the TV's existing registry as a read-only seed. With registry updates
    # disabled, an empty private path would have no registered vendor factories.
    (run / 'registry.bin').write_bytes(Path('/mnt/flash/data/gst_1_0_registry.arm.bin').read_bytes())
    os.chmod(str(run / 'registry.bin'), 0o600)
    os.environ.update(GST_REGISTRY=str(run / 'registry.bin'), GST_DEBUG_FILE=str(run / 'gst.log'), GST_DEBUG='0')
    stopped = [False]
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda *_: stopped.__setitem__(0, True))
    # Native contexts contain stream bytes; never persist process core dumps.
    limits = (C.c_ulong * 2)(0, 0)
    C.CDLL(None).setrlimit(4, C.byref(limits))
    def alive():
        try:
            return identity(args.pid) == original
        except (OSError, RuntimeError):
            return False
    journal = {}
    def report(phase, **values):
        journal.update(phase=phase, nativePid=args.pid, **values)
        temp = run / 'status.tmp'
        temp.write_text(json.dumps(journal))
        temp.replace(run / 'status.json')
    from runtime import Tv
    tv = Tv()
    output = Output(tv, report)
    channel = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    success = False
    try:
        channel.settimeout(3)
        channel.connect(str(args.socket))
        pid, uid, _ = struct.unpack('3i', channel.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if pid != args.pid or uid != original[0] or not alive():
            raise RuntimeError('MAT socket peer differs')
        output.preflight()
        report('ready', systemOrPluginsModified=False)
        serve(channel, output, alive, stopped, report)
        success = True
    except BaseException as error:
        report('failed', errorClass=type(error).__name__,
               reason=str(error) if isinstance(error, (RuntimeError, ValueError)) else 'operation failed')
    finally:
        clean = output.close()
        try:
            channel.sendall(b'C' if clean else b'E')
        except OSError:
            pass
        channel.close()
        tv.close()
    return 0 if success and clean else 1


if __name__ == '__main__':
    sys.exit(main())
