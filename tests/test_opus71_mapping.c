#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <opus_multistream.h>
#include "opus71_mapping.h"

int main(void) {
    const int vorbis_to_wav[8] = {0, 2, 1, 6, 7, 4, 5, 3};
    for (int high = 0; high < 2; ++high) {
        unsigned char wav_map[8] = {0, 1, 6, 7, 2, 3, 4, 5};
        if (high) for (int i = 0; i < 8; ++i) wav_map[i] = (unsigned char)i;
        unsigned char vorbis_map[8];
        moonlight_opus71_vorbis_mapping(vorbis_map, wav_map);
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
    puts("PASS: Windows-to-Vorbis positions for all 8 channels, standard and high-quality Opus");
    return 0;
}
