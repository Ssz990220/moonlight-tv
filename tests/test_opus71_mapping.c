#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <opus_multistream.h>
#include "opus71_mapping.h"

int main(void) {
    const int vorbis_to_wav[8] = {0, 2, 1, 6, 7, 4, 5, 3};
    const unsigned char affected[8] = {0, 1, 2, 7, 4, 5, 3, 6};
    unsigned char unchanged[8];
    assert(!moonlight_opus71_sunshine_mapping(unchanged, affected, 5, 3, true));
    assert(memcmp(unchanged, affected, 8) == 0);
    assert(!moonlight_opus71_sunshine_mapping(unchanged, affected, 8, 0, false));
    for (int mode = 0; mode < 3; ++mode) {
        int high = mode == 1;
        unsigned char wav_map[8] = {0, 1, 6, 7, 2, 3, 4, 5};
        if (high || mode == 2) for (int i = 0; i < 8; ++i) wav_map[i] = (unsigned char)i;
        unsigned char callback_map[8];
        memcpy(callback_map, wav_map, 8);
        if (mode == 2) {
            /* Reproduce Sunshine's three-entry rotation and the client's
             * five-entry GFE correction, rather than assuming the result. */
            unsigned char advertised[8];
            memcpy(advertised, wav_map, 8);
            advertised[3]=wav_map[4]; advertised[4]=wav_map[5]; advertised[5]=wav_map[3];
            callback_map[3]=advertised[7];
            memcpy(callback_map+4,advertised+3,4);
            assert(memcmp(callback_map, affected, 8) == 0);
        }
        unsigned char corrected[8];
        assert(moonlight_opus71_sunshine_mapping(corrected, callback_map,
                    high ? 8 : 5, high ? 0 : 3, false) == (mode == 2));
        assert(memcmp(corrected, wav_map, 8) == 0);
        unsigned char vorbis_map[8];
        moonlight_opus71_vorbis_mapping(vorbis_map, corrected);
        for (int i = 0; i < 8; ++i) assert(vorbis_map[i] == wav_map[vorbis_to_wav[i]]);
        int error;
        OpusMSEncoder *encoder = opus_multistream_encoder_create(48000, 8, high ? 8 : 5, high ? 0 : 3,
            wav_map, OPUS_APPLICATION_RESTRICTED_LOWDELAY, &error);
        assert(encoder && error == OPUS_OK);
        opus_multistream_encoder_ctl(encoder, OPUS_SET_BITRATE(high ? 2048000 : 450000));
        OpusMSDecoder *decoder = opus_multistream_decoder_create(48000, 8, high ? 8 : 5, high ? 0 : 3,
            vorbis_map, &error);
        assert(decoder && error == OPUS_OK);
        for (int wav_channel = 0; wav_channel < 8; ++wav_channel) {
            opus_multistream_encoder_ctl(encoder, OPUS_RESET_STATE);
            opus_multistream_decoder_ctl(decoder, OPUS_RESET_STATE);
            double energy[8] = {0};
            int expected = -1;
            for (int i = 0; i < 8; ++i) if (vorbis_to_wav[i] == wav_channel) expected = i;
            assert(expected >= 0);
            for (int frame = 0; frame < 12; ++frame) {
                float input[240 * 8] = {0}, output[240 * 8];
                for (int i = 0; i < 240; ++i) input[i * 8 + wav_channel] = .1f * sinf((frame * 240 + i) * .1f);
                unsigned char packet[8192];
                int size = opus_multistream_encode_float(encoder, input, 240, packet, sizeof(packet));
                assert(size > 0);
                int count = opus_multistream_decode_float(decoder, packet, size, output, 240, 0);
                assert(count == 240);
                for (int i = 0; i < count; ++i)
                    for (int c = 0; c < 8; ++c) energy[c] += output[i * 8 + c] * output[i * 8 + c];
            }
            assert(energy[expected] > 1);
            for (int c = 0; c < 8; ++c) if (c != expected) assert(energy[c] < energy[expected] * .02);
        }
        opus_multistream_decoder_destroy(decoder);
        opus_multistream_encoder_destroy(encoder);
    }
    puts("PASS: 24 isolated channel roundtrips; standard, HQ and observed Sunshine SDP rotation");
    return 0;
}
