#define _POSIX_C_SOURCE 200809L
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* webOS native application entry points must be ELF executables. The supervisor
 * and preload library live inside this separate application's installation. */
int main(int argc, char **argv) {
    char root[PATH_MAX], script[PATH_MAX], binary[PATH_MAX];
    ssize_t size = readlink("/proc/self/exe", root, sizeof(root) - 1);
    if (size <= 0 || size >= (ssize_t)sizeof(root) - 1) return 1;
    root[size] = 0;
    char *last = strrchr(root, '/');
    if (!last) return 1;
    *last = 0;
    last = strrchr(root, '/');
    if (!last) return 1;
    *last = 0;
    if (snprintf(script, sizeof(script), "%s/libexec/opus71_session.py", root) >= (int)sizeof(script) ||
        snprintf(binary, sizeof(binary), "%s/bin/moonlight", root) >= (int)sizeof(binary)) return 1;
    char **python_args = calloc((size_t)argc + 5, sizeof(char *));
    if (!python_args) return 1;
    python_args[0] = "python3";
    python_args[1] = "-B";
    python_args[2] = script;
    python_args[3] = root;
    for (int i = 1; i < argc; ++i) python_args[i + 3] = argv[i];
    execvp(python_args[0], python_args);
    free(python_args);
    fputs("Moonlight Opus71: supervisor unavailable; using original audio capabilities.\n", stderr);
    unsetenv("SS4S_WEBOS_OPUS71");
    unsetenv("SS4S_OPUS71_NOTIFY_FD");
    argv[0] = binary;
    execv(binary, argv);
    return 1;
}
