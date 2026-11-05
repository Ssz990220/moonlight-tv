/* SPDX-License-Identifier: GPL-3.0-or-later */
#define _GNU_SOURCE
#include "session_mat.h"
#include <Limelight.h>

#if TARGET_WEBOS
#include "mat_receiver_hashes.h"
#include "MatReceiver.h"
#include <errno.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

extern bool webos_root_exec(const char *command);
static int channel = -1;
static char folder[64], endpoint[100];
static uint64_t cycles, epoch_id, domain_id;

static int64_t now_ms(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (int64_t)t.tv_sec * 1000 + t.tv_nsec / 1000000;
}

static bool send_bytes(const void *data, size_t size) {
    const unsigned char *p = data;
    int64_t deadline = now_ms() + 1000;
    while (size && now_ms() < deadline) {
        ssize_t n = send(channel, p, size, MSG_NOSIGNAL | MSG_DONTWAIT);
        if (n > 0) { p += n; size -= (size_t)n; continue; }
        if (n < 0 && errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) return false;
        struct pollfd fd = {channel, POLLOUT, 0};
        if (poll(&fd, 1, 20) < 0 && errno != EINTR) return false;
    }
    return !size;
}

static bool reply(char expected, int timeout) {
    struct pollfd fd = {channel, POLLIN, 0};
    char c;
    return channel >= 0 && poll(&fd, 1, timeout) > 0 &&
           recv(channel, &c, 1, MSG_DONTWAIT) == 1 && c == expected;
}

static void put32(unsigned char *p, uint32_t v) {
    for (int i = 0; i < 4; ++i) p[i] = (unsigned char)(v >> (8 * i));
}
static void put64(unsigned char *p, uint64_t v) { put32(p, (uint32_t)v); put32(p + 4, (uint32_t)(v >> 32)); }
static uint32_t checksum(const unsigned char *p, size_t n) {
    // Per-session callbacks are serialized by common-c's audio thread.
    static uint32_t table[256];
    static bool ready;
    if (!ready) {
        for (unsigned i = 0; i < 256; ++i) {
            uint32_t v = i;
            for (int j = 0; j < 8; ++j) v = (v >> 1) ^ ((v & 1) ? 0xedb88320u : 0);
            table[i] = v;
        }
        ready = true;
    }
    uint32_t v = 0xffffffffu;
    while (n--) v = table[(v ^ *p++) & 255] ^ (v >> 8);
    return v ^ 0xffffffffu;
}
static bool record(const char *magic, uint64_t index, uint64_t pts, const unsigned char *data, size_t n) {
    unsigned char h[32] = {0};
    memcpy(h, magic, 4); put32(h + 4, 1); put64(h + 8, index); put64(h + 16, pts);
    put32(h + 24, (uint32_t)n); put32(h + 28, data ? checksum(data, n) : 0);
    return send_bytes(h, sizeof(h)) && (!n || send_bytes(data, n));
}

static int cycle(void *ctx, const unsigned char *data, int n, uint64_t epoch, uint64_t domain,
                 uint64_t index, uint64_t pts) {
    (void)ctx;
    if (channel < 0 || n != 61440 || !MatCarrierIsValid(data, (size_t)n) || !epoch || !domain ||
        index != cycles || pts != index * 960 ||
        (cycles && (epoch != epoch_id || domain != domain_id))) return 0;
    if (!cycles) { epoch_id = epoch; domain_id = domain; }
    if (!record("TVMT", index, pts, data, (size_t)n)) return 0;
    ++cycles;
    return 1;
}
static int end(void *ctx, uint64_t count) {
    (void)ctx;
    return channel >= 0 && count && count == cycles &&
           record("TVME", count, count * 960, NULL, 0) && reply('D', 3000);
}

bool session_mat_prepare(void) {
    if (channel >= 0) return false;
    const char *root = getenv("HOME");
    static const char *allowed[] = {
        "/media/developer/apps/usr/palm/applications/com.ssz990220.moonlight.opus71",
        "/media/cryptofs/apps/usr/palm/applications/com.ssz990220.moonlight.opus71",
        "/usr/palm/applications/com.ssz990220.moonlight.opus71"};
    bool valid = false;
    for (size_t i = 0; root && i < sizeof(allowed) / sizeof(allowed[0]); ++i)
        valid |= strcmp(root, allowed[i]) == 0;
    if (!valid) return false;
    strcpy(folder, "/tmp/moonlight-mat-XXXXXX");
    if (!mkdtemp(folder)) { folder[0] = 0; return false; }
    snprintf(endpoint, sizeof(endpoint), "%s/audio", folder);
    int listener = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (listener < 0) goto fail;
    struct sockaddr_un address = {.sun_family = AF_UNIX};
    strcpy(address.sun_path, endpoint);
    if (bind(listener, (struct sockaddr *)&address, sizeof(address)) || listen(listener, 1)) goto fail;
    char command[3900];
    int length = snprintf(command, sizeof(command),
        "/usr/bin/python3 -I -B -c 'import hashlib; p=\"%s/libexec/mat/receiver.py\"; "
        "d=open(p,\"rb\").read(); assert hashlib.sha256(d).hexdigest()==\"%s\"; "
        "exec(compile(d,p,\"exec\"),{\"__name__\":\"__main__\",\"__file__\":p})' "
        "--pid %ld --root '%s' --socket '%s' --manifest-sha %s >/dev/null 2>&1 </dev/null &",
        root, MAT_RECEIVER_SHA, (long)getpid(), root, endpoint, MAT_MANIFEST_SHA);
    if (length <= 0 || length >= (int)sizeof(command) || !webos_root_exec(command)) goto fail;
    struct pollfd fd = {listener, POLLIN, 0};
    if (poll(&fd, 1, 6000) <= 0) goto fail;
    channel = accept4(listener, NULL, NULL, SOCK_CLOEXEC | SOCK_NONBLOCK);
    close(listener); listener = -1;
    if (channel < 0) goto fail;
    struct ucred peer;
    socklen_t len = sizeof(peer);
    // Only the root broker may receive authenticated payload bytes.
    if (getsockopt(channel, SOL_SOCKET, SO_PEERCRED, &peer, &len) || peer.uid != 0 || !reply('R', 6000)) goto fail;
    cycles = epoch_id = domain_id = 0;
    return true;
fail:
    if (listener >= 0) close(listener);
    session_mat_close();
    return false;
}

bool session_mat_open(void) {
    if (channel < 0 || !record("TVMS", 7, 48000, NULL, 0) || !reply('S', 6000)) return false;
    LI_MAT_PLAYBACK_CALLBACKS callbacks = {cycle, end, NULL};
    LiSetMatPlaybackCallbacks(&callbacks);
    return true;
}

void session_mat_close(void) {
    LiSetMatPlaybackCallbacks(NULL);
    if (channel >= 0) {
        // EOF abandons an interrupted stream; never synthesize authenticated EOS.
        shutdown(channel, SHUT_WR);
        reply('C', 4000); // root helper acknowledges hardware cleanup
        close(channel);
        channel = -1;
    }
    if (endpoint[0]) unlink(endpoint);
    if (folder[0]) rmdir(folder);
    endpoint[0] = folder[0] = 0;
    cycles = epoch_id = domain_id = 0;
}
#else
bool session_mat_prepare(void) { return false; }
bool session_mat_open(void) { return false; }
void session_mat_close(void) { LiSetMatPlaybackCallbacks(NULL); }
#endif
