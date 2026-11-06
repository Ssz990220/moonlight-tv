#pragma once

/* Read-only socket metadata. No addresses, ports, or packet contents. */
#include <stdio.h>
#include <sys/socket.h>
#include <sys/stat.h>

static inline int stream_udp_row(const char *line, unsigned long wanted,
                                 long *queued, long *drops) {
    unsigned int tx, rx;
    unsigned long inode, lost;
    if (sscanf(line, "%*u: %*s %*s %*s %x:%x %*s %*s %*u %*u %lu %*u %*s %lu",
               &tx, &rx, &inode, &lost) != 4 || inode != wanted) return 0;
    *queued = (long)rx;
    *drops = (long)lost;
    return 1;
}

static inline void stream_audio_diagnostics(int fd, int *buffer, long *queued, long *drops) {
    *buffer = -1; *queued = -1; *drops = -1;
    if (fd < 0) return;
    socklen_t size = sizeof(*buffer);
    if (getsockopt(fd, SOL_SOCKET, SO_RCVBUF, buffer, &size) != 0) *buffer = -1;
#ifdef __linux__
    struct stat info;
    if (fstat(fd, &info) != 0) return;
    const char *tables[] = {"/proc/net/udp", "/proc/net/udp6"};
    for (unsigned i = 0; i < sizeof(tables) / sizeof(tables[0]); i++) {
        FILE *file = fopen(tables[i], "r");
        if (!file) continue;
        char line[1024];
        int found = 0;
        while (fgets(line, sizeof(line), file)) {
            if (stream_udp_row(line, (unsigned long)info.st_ino, queued, drops)) {
                found = 1;
                break;
            }
        }
        fclose(file);
        if (found) break;
    }
#endif
}
