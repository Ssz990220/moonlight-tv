#define _POSIX_C_SOURCE 200809L
#include <ctype.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <SDL.h>
#include "lunasynccall.h"
#include "opus71_root_hashes.h"

static void *request_root(void *argument) {
    char *root = argument;
    char command[4096], escaped[8192], payload[8400];
    int n = snprintf(command, sizeof(command),
        "/usr/bin/python3 -I -B -c 'import hashlib; p=\"%s/libexec/opus71_root.py\"; "
        "d=open(p,\"rb\").read(); assert hashlib.sha256(d).hexdigest()==\"%s\"; "
        "exec(compile(d,p,\"exec\"))' --pid %ld --root '%s' --worker-sha %s "
        ">/dev/null 2>&1 </dev/null &", root, OPUS71_ROOT_SHA, (long)getpid(), root, OPUS71_POLICY_SHA);
    free(root);
    if (n <= 0 || n >= (int)sizeof(command)) return NULL;
    size_t out = 0;
    for (int i = 0; i < n; ++i) {
        if (command[i] == '"' || command[i] == '\\') escaped[out++] = '\\';
        escaped[out++] = command[i];
    }
    escaped[out] = 0;
    snprintf(payload, sizeof(payload), "{\"command\":\"%s\"}", escaped);
    char *reply = NULL;
    int sent = HLunaServiceCallSync("luna://org.webosbrew.hbchannel.service/exec", payload, true, &reply);
    printf("Root route bridge: %s\n", sent ? "request delivered; authorization must be checked" : "request unavailable");
    free(reply);
    return NULL;
}

void opus71_root_bridge_start(void) {
    const char *root = SDL_getenv("HOME");
    if (!root) return;
    static const char *allowed[] = {
        "/media/developer/apps/usr/palm/applications/com.ssz990220.moonlight.opus71",
        "/media/cryptofs/apps/usr/palm/applications/com.ssz990220.moonlight.opus71",
        "/usr/palm/applications/com.ssz990220.moonlight.opus71"};
    int valid = 0;
    for (size_t i = 0; i < sizeof(allowed)/sizeof(allowed[0]); ++i) valid |= strcmp(root, allowed[i]) == 0;
    if (!valid) return;
    char *copy = strdup(root);
    if (!copy) return;
    pthread_t thread;
    if (pthread_create(&thread, NULL, request_root, copy)) free(copy);
    else pthread_detach(thread);
}
