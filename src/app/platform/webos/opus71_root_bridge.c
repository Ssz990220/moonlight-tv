#define _POSIX_C_SOURCE 200809L
#include <ctype.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <SDL.h>
#include <luna-service2/lunaservice.h>
#include "opus71_root_hashes.h"

static bool root_reply(LSHandle *handle, LSMessage *message, void *data) {
    (void)handle;
    printf("Root route bridge: %s\n", LSMessageIsHubErrorMessage(message) ? "hub rejected request" : "reply received; status verified separately");
    g_main_loop_quit(data);
    return false;
}
static gboolean root_timeout(gpointer data) {
    printf("Root route bridge: request timed out\n");
    g_main_loop_quit(data);
    return G_SOURCE_REMOVE;
}

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
    GMainContext *context = g_main_context_new();
    GMainLoop *loop = g_main_loop_new(context, FALSE);
    LSHandle *handle = NULL;
    LSError error;
    LSErrorInit(&error);
    LSMessageToken token = 0;
    /* A normal native executable is an ordinary LS2 client, not a web-app
     * proxy entitled to register an application identity. Preserve its actual
     * UID/executable credentials and let the hub enforce public API policy. */
    if (LSRegister(NULL, &handle, &error) &&
        LSGmainContextAttach(handle, context, &error) &&
        LSCallOneReply(handle, "luna://org.webosbrew.hbchannel.service/exec", payload,
                       root_reply, loop, &token, &error)) {
        GSource *timeout = g_timeout_source_new(5000);
        g_source_set_callback(timeout, root_timeout, loop, NULL);
        g_source_attach(timeout, context);
        g_main_loop_run(loop);
        g_source_destroy(timeout);
        g_source_unref(timeout);
    } else {
        printf("Root route bridge: registration or call unavailable (code %d)\n", error.error_code);
    }
    if (handle) LSUnregister(handle, &error);
    LSErrorFree(&error);
    g_main_loop_unref(loop);
    g_main_context_unref(context);
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
