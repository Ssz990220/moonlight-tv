#include <assert.h>
#include <unistd.h>
#include "stream_diagnostics.h"

int main(void) {
    long queued = -1, drops = -1;
    const char *row = " 123: 00000000:1234 00000000:0000 07 00000000:00010000 "
                      "00:00000000 00000000 1000 0 2468 2 00000000 17";
    assert(stream_udp_row(row, 2468, &queued, &drops));
    assert(queued == 65536 && drops == 17);
    assert(!stream_udp_row(row, 1357, &queued, &drops));
    assert(!stream_udp_row("malformed", 2468, &queued, &drops));
    int buffer;
    stream_audio_diagnostics(-1, &buffer, &queued, &drops);
    assert(buffer == -1 && queued == -1 && drops == -1);
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    assert(fd >= 0);
    stream_audio_diagnostics(fd, &buffer, &queued, &drops);
    assert(buffer > 0);
    close(fd);
    return 0;
}
