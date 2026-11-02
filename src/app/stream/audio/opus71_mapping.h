#pragma once
#include <string.h>

/* moonlight-common-c supplies WAV order: FL FR C LFE BL BR SL SR.
 * RFC 7845 mapping family 1 uses: FL C FR SL SR BL BR LFE.
 * Reorder the mapping table only, never the encoded audio packets.
 */
static inline void moonlight_opus71_vorbis_mapping(unsigned char out[8], const unsigned char in[8]) {
    static const unsigned char wav_index[8] = {0, 2, 1, 6, 7, 4, 5, 3};
    unsigned char copy[8];
    memcpy(copy, in, 8);
    for (int i = 0; i < 8; ++i) out[i] = copy[wav_index[i]];
}
