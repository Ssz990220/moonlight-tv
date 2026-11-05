#include <Limelight.h>
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
static int codec;
static const char original[] = "v=0\r\ns=Client \r\na=x-ml-audio.codec:mat-live \r\na=test:two words  \r\nm=video 48010  \r\n";
int LiGetNegotiatedAudioCodec(void) { return codec; }
char *__real_getSdpPayloadForStreamConfig(int version, int *length) {
    assert(version == 14); *length = (int)strlen(original);
    char *p = malloc(sizeof(original)); assert(p); memcpy(p, original, sizeof(original)); return p;
}
char *__wrap_getSdpPayloadForStreamConfig(int, int *);
int main(void) {
    int length;
    codec = AUDIO_CODEC_OPUS;
    char *p = __wrap_getSdpPayloadForStreamConfig(14, &length);
    assert(length == (int)strlen(original) && !memcmp(p, original, sizeof(original))); free(p);
    codec = AUDIO_CODEC_MAT_LIVE;
    p = __wrap_getSdpPayloadForStreamConfig(14, &length);
    const char compact[] = "v=0\r\ns=Client \r\na=x-ml-audio.codec:mat-live\r\na=test:two words \r\nm=video 48010  \r\n";
    assert(length == (int)strlen(compact) && !memcmp(p, compact, sizeof(compact))); free(p);
    puts("PASS MAT SDP formatting and exact Opus fallback preservation");
    return 0;
}
