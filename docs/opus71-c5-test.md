# LG C5 Opus 7.1 test build

This is an unvalidated, separate application (`com.ssz990220.moonlight.opus71`,
version 1.6.99). It does not replace `com.limelight.webos`, DTS Enabler, any system
library, or a GStreamer plugin. No installer, boot service, root escalation,
firmware change, or automatic television connection is included.

## Audio path

Windows eight-channel audio -> Sunshine Opus multistream -> SS4S NDL -> native
LG Opus decoder -> native PCM8/acmod21 -> temporary eARC LPCM8 request.
Standard (5 streams / 3 coupled) and high-quality (8 streams / 0 coupled) 7.1
configurations are accepted. Moonlight converts its Windows-order mapping table
to the Vorbis-order table required by OpusHead family 1. Encoded packets are not re-encoded or reordered by
the new eight-channel path. This is not TrueHD/DTS/Atmos passthrough or a lossless
network audio mode.

For the experimental native eight-channel backend, version 1.6.98 requests
standard Opus independently of video bitrate. In 1.6.97 the phone confirmed
7.1 using the 14 Mbps video/standard-Opus comparison; the 95 Mbps/HQ attempt did
not establish a verified receiver output. This does not yet prove an intrinsic
HQ decoder limitation. Video bitrate is restored separately to the user's
original 95 Mbps; resolution and frame rate remain 3840x2160/120.

The observed normal-mode callback map was `0,1,2,7,4,5,3,6`, producing a header
map `0,2,1,3,6,4,5,7`. Sunshine's `src/rtsp.cpp` rotates only the range ending at
`audio::MAX_STREAM_CONFIG` (six configurations), whereas moonlight-common-c
reverses the GFE rotation over eight channels. With Sunshine's identity encoder
map this exactly predicts SUB->SL, SL->SR and SR->SUB, matching the user's
report. Only this non-GFE 5-stream/3-coupled signature is corrected to the
identity Windows map before Windows-to-Vorbis conversion. GFE, custom and HQ
maps pass through unchanged. Real-libopus tests reproduce both protocol
rotations and check all eight speaker positions. Physical verification of the
corrected build is still pending.

The bootstrap is linked into `bin/moonlight` and re-execs that same registered
executable, preserving both the original PID and the LS2 executable identity.
The older separate launcher caused `LSHUB_NO_ROLE_FILE` when NDL created its
resource manager and aborted on the first streaming attempt. Version 1.6.95
corrects this packaging error without adding or editing any LS2 role files.
An optional Python child handles policy and filtered startup diagnostics; no PTY is needed.
Video capability probing now treats the MRC API's boolean `true` as success and
retains its maximum frame rate. The C5's read-only HEVC result is 4096x2304 at
120 FPS; this restores preset eligibility, not proof of a successful 4K120 stream.

SS4S's 7.1 experiment is compiled off by default. The app-local bootstrap enables
it only in its own child process and preloads an app-local library. That shim
preserves the negotiated full OpusHead before LG's native decoder consumes it.
The C5 NDL API rejects `OPUS 8ch` in AudioDataSetting before constructing its
decoder. Version 1.6.96 uses its accepted six-channel creation descriptor, then
replaces the compressed-input CAPS with the real eight-channel full OpusHead
at the app-owned decoder's sink pad. It removes the obsolete six-channel mask.
On the actual 1.6.96 streaming test the downstream player retained six-channel
metadata and Sonos reported 5.1 with rear-left/rear-right missing. Version 1.6.97
also intercepts NDL's existing StarfishMediaAPIs::Load boundary to restore the
real eight-channel/full-header configuration there, restricted to this app's
DIRECTMEDIA-ES-PLAYER OPUS load. All other metadata and inactive/ordinary loads
pass through unchanged. json-c is resolved from the existing runtime library.
The adapter is tested against a mock ABI-compatible downstream Load function;
whether the native decoder accepts that configuration still needs a TV test.
The decoded-output guard below is unchanged and never relabels PCM6 as PCM8.
On that process's LG audio sink it requires actual native eight-channel,
48 kHz Opus output with `acmod=(uint)21`; it does not relabel padded 5.1
(`acmod=7`) as 7.1. Eligible caps retain codec17 and gain `out-channels=(int)8`
and LFE enabled. The app-owned sink's PCM bypass/multichannel switches are false,
matching the previously observed native LPCM7.1 route. Original property values
are saved and restored if still owned.

The ordinary app child publishes only bounded session generations and native
CAPS proof. The native app requests Homebrew Channel's existing `exec` API to
start an app-owned root broker, after verifying both Python scripts against
SHA256 constants compiled into the native client. This does not install a boot
service, add roles/groups, or change system or existing plugin files.

The broker is tied to the original native PID and start time, exits with the app
(or after six hours), and keeps its lock/status only in a root-owned temporary
directory. It requires the app's active-session journal AND independent kernel
PCM8/acmod21 converter evidence. Only with this app foreground, Digital Sound
Output=Auto, eARC On and PCM8 receiver support may it request
`Sndout EARC Outputtype=[2,1,8,0,1]`. It never enables OTT/MAT. It restores only its
own app/output/control lease. No media/account URLs are collected by the broker.

The TV must already have a rooted Homebrew Channel permitting this application
to call `exec`. A rejected request does not change permissions or system files;
it leaves the automatic output route unavailable. Native Opus decoding and the
receiver's actual format remain separate verification stages.

If the platform SDK query fails, the client can read `conf/device-sdk-version`.
The installer obtains this public version from the actual TV and writes it only
inside the separate app; no version is guessed, bundled, or used to override a
successful system query. Missing/invalid metadata leaves version detection failed.

## Validation before installation

`third_party/ss4s/tests/run-opus71-tests.sh` tests malformed/truncated headers,
CAPS preservation and sixteen isolated channel roundtrips through real libopus,
under AddressSanitizer/UndefinedBehaviorSanitizer, without an audio device.
`tests/test_opus71_mapping.c` additionally checks all eight Windows-to-Vorbis
speaker positions through real Opus encoding/decoding in both quality modes.
`python3 -B tests/test_opus71_policy.py` tests proof/eligibility gates, restoration,
permission failures and user/app transitions using mocks.

GitHub Actions builds a complete ARM IPK with the webOS NDK. Its artifact includes
source revisions and binary SHA256 values. Building an IPK does not validate
LG's native handling of the supplied Opus mapping or physical speaker positions.
Factory symbol interposition, native decoder output, jail permissions, latency,
reconnect behavior and all eight receiver channels still require a TV test.

## Later manual test

Install the separate IPK only when authorized. Pair the separate client with
Windows Sunshine; select webOS NDL and 7.1. Confirm Sunshine logs eight-channel
Opus and a Windows capture endpoint capable of 7.1. Leave the existing DTS plugin
unchanged. For the LPCM route use TV HDMI eARC, eARC On, Digital Sound Output Auto.
Confirm Sonos says **Multichannel PCM 7.1**, then test FL, FR, C, LFE, SL, SR, BL,
BR individually. A format badge alone is not proof of correct channel mapping.
Compare 5.1/stereo, standard/high-quality Opus, reconnect and app-exit restoration.
No television testing was performed during preparation of this build.

## Live MAT receiver in 1.6.99

Audio Settings has a Streaming audio format entry: Auto, Opus, or Require Dolby
Atmos / MAT. Auto is the default for a configuration without this entry. It
preflights the TV and requests the host's live MAT profile, selecting Opus before
ANNOUNCE if the host does not advertise a ready source. GFE, unavailable Homebrew
Channel, unsupported native library hashes, and unavailable eARC capability select
Opus in Auto. Require MAT reports an error in those cases. The existing Sound
Channels setting is preserved and controls Opus, including the Auto fallback.
No live format switching occurs after audio has started: a failed or corrupted
MAT transport ends that session rather than interpreting its bytes as Opus.

The pinned common-c fork provides authenticated live MAT codec 7, whole-carrier
validation, and authenticated end-of-stream. A per-session root helper is requested
through the already available Homebrew Channel exec API. It checks the registered
Moonlight process identity, exact helper hashes, local socket peer credentials,
foreground application, eARC settings, native MAT format, and the audited C5
library hashes before using a separately reserved ADEC. No system/plugin code,
roles, drivers, or boot services are modified. The helper relinquishes its route
if the app/output changes, and releases its resources on EOF, parent exit, or
source timeout. Only bounded local socket frames carry MAT; no pairing material
is passed to the helper. The existing NDL player handles video without opening
its own audio decoder.

This reuses the standalone receiver's native ES/HBR output: byte-swap the encoded
carrier's 16-bit words, retain the MAT payload, and temporarily request the verified
[2,6,8,0,0] eARC transport after native format discovery. The auxiliary MAT decoder
is used only for the first two cycles of format discovery. It is not the output
PCM path. The transport's legacy enum label is not a TrueHD conversion.

A separate standalone test verified 30.72 seconds / 1,536 complete live MAT cycles
from two generated Windows spatial objects on Steam Streaming Speakers to Sonos
Dolby Atmos (MAT), with matching publisher/receiver hashes and zero sink drops.
That test was muted and did not establish audible object placement or video sync.
The integrated app requires its own TV validation; the independent system clock
and 200 ms audio prebuffer are experimental, not a calibrated AV sync guarantee.
This app does not install or start Foundation's Windows object capture hooks.
Foundation must already have a compatible live capture source when MAT is selected.

Live MAT/Auto requests use the common-c decoder queue so local IPC and native
format discovery cannot block the network/FEC receive thread. Explicit Opus
retains its original direct-submit behavior. Version 1.6.100 also compacts only
the MAT SDP formatting spaces to fit Foundation’s encrypted RTSP size limit;
Opus SDP remains byte-identical.
