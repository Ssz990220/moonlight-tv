/* SPDX-License-Identifier: GPL-3.0-or-later
 * Foundation's encrypted RTSP request limit includes the ANNOUNCE headers.
 * The common-c SDP serializer appends one optional formatting space to each
 * attribute. Remove just that formatting byte for live MAT; retain every
 * attribute/value and leave Opus (including Auto fallback) byte-identical.
 */
#include <Limelight.h>
#include <stdlib.h>
#include <string.h>

extern char *__real_getSdpPayloadForStreamConfig(int version, int *length);

char *__wrap_getSdpPayloadForStreamConfig(int version, int *length) {
    char *payload = __real_getSdpPayloadForStreamConfig(version, length);
    if (!payload || LiGetNegotiatedAudioCodec() != AUDIO_CODEC_MAT_LIVE) return payload;
    size_t read = 0, written = 0, n = (size_t)*length;
    while (read < n) {
        size_t end = read;
        while (end + 1 < n && !(payload[end] == '\r' && payload[end + 1] == '\n')) ++end;
        if (end + 1 >= n) {
            memmove(payload + written, payload + read, n - read);
            written += n - read;
            break;
        }
        size_t bytes = end - read;
        if (bytes >= 3 && payload[read] == 'a' && payload[read + 1] == '=' && payload[end - 1] == ' ') --bytes;
        memmove(payload + written, payload + read, bytes);
        written += bytes;
        payload[written++] = '\r'; payload[written++] = '\n';
        read = end + 2;
    }
    payload[written] = '\0';
    *length = (int)written;
    return payload;
}
