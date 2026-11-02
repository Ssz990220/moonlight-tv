#pragma once
#include <string.h>
#include <stdbool.h>

/* Sunshine's normal 7.1 SDP rotates [3, MAX_STREAM_CONFIG=6), while
 * moonlight-common-c reverses the GFE rotation over all eight channels.
 * Its identity encoder map therefore arrives as 0,1,2,7,4,5,3,6.
 * Match only that observed signature: GFE, custom and HQ maps pass through.
 */
static inline bool moonlight_opus71_sunshine_mapping(unsigned char out[8], const unsigned char in[8],
                                                    int streams, int coupled, bool is_gfe) {
    static const unsigned char affected[8] = {0, 1, 2, 7, 4, 5, 3, 6};
    memcpy(out, in, 8);
    if (is_gfe || streams != 5 || coupled != 3 || memcmp(in, affected, 8) != 0) return false;
    for (int i = 0; i < 8; ++i) out[i] = (unsigned char)i;
    return true;
}

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
