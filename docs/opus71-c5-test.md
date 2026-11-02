# LG C5 Opus 7.1 test build

This is an unvalidated, separate application (`com.ssz990220.moonlight.opus71`,
version 1.6.90). It does not replace `com.limelight.webos`, DTS Enabler, any system
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

SS4S's 7.1 experiment is compiled off by default. The separate launcher enables
it only in its own child process and preloads an app-local library. That shim
preserves the negotiated full OpusHead before LG's native decoder consumes it.
On that process's LG audio sink it requires actual native eight-channel,
48 kHz Opus output with `acmod=(uint)21`; it does not relabel padded 5.1
(`acmod=7`) as 7.1. Eligible caps retain codec17 and gain `out-channels=(int)8`
and LFE enabled. The app-owned sink's PCM bypass/multichannel switches are false,
matching the previously observed native LPCM7.1 route. Original property values
are saved and restored if still owned.

The Python supervisor waits for a current-session CAPS notification and fresh
kernel native first-format/converter evidence. Only with this app foreground,
Digital Sound Output=Auto, eARC On, an active eARC link and advertised eight-channel
PCM receiver support may it request `Sndout EARC Outputtype=[2,1,8,0,1]`. It does
not enable OTT/MAT. It snapshots the old value and restores it at session end
only if the app, output settings and current control value still match its lease.
A user/app/output change relinquishes the lease instead of being overwritten.

The supervisor requires existing `python3`, `luna-send`, `dmesg` and `amixer`
access. It does not grant itself extra permissions. Permission or proof failures
leave the route unmodified. If Python is absent, the launcher uses original
six-channel capabilities. A missing shim also leaves SS4S capped at six channels.

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
