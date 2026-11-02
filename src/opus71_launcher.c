#define _POSIX_C_SOURCE 200809L
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

/* Keep webOS's application PID as native Moonlight; policy is only a child. */
int main(int argc, char **argv) {
    (void)argc;
    char root[PATH_MAX], script[PATH_MAX], binary[PATH_MAX], shim[PATH_MAX];
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
        snprintf(binary, sizeof(binary), "%s/bin/moonlight", root) >= (int)sizeof(binary) ||
        snprintf(shim, sizeof(shim), "%s/lib/libss4s-opus71-route.so", root) >= (int)sizeof(shim)) return 1;
    int event[2], ready[2], log[2];
    if (pipe(event) || pipe(ready) || pipe(log)) return 1;
    pid_t parent = getpid();
    pid_t child = fork();
    if (child == 0) {
        close(event[1]); close(ready[0]); close(log[1]);
        char parent_arg[24], event_arg[24], ready_arg[24], log_arg[24];
        snprintf(parent_arg, sizeof(parent_arg), "%ld", (long)parent);
        snprintf(event_arg, sizeof(event_arg), "%d", event[0]);
        snprintf(ready_arg, sizeof(ready_arg), "%d", ready[1]);
        snprintf(log_arg, sizeof(log_arg), "%d", log[0]);
        execlp("python3", "python3", "-B", script, "--worker", root,
               parent_arg, event_arg, ready_arg, log_arg, (char *)NULL);
        _exit(127);
    }
    close(event[0]); close(ready[1]); close(log[0]);
    struct pollfd check = {.fd = ready[0], .events = POLLIN};
    char ack = 0;
    int started = child > 0 && poll(&check, 1, 4000) > 0 && read(ready[0], &ack, 1) == 1 && ack == '1';
    close(ready[0]);
    if (started) {
        char event_arg[24];
        snprintf(event_arg, sizeof(event_arg), "%d", event[1]);
        fcntl(event[1], F_SETFL, fcntl(event[1], F_GETFL) | O_NONBLOCK);
        setenv("SS4S_WEBOS_OPUS71", "1", 1);
        setenv("SS4S_OPUS71_NOTIFY_FD", event_arg, 1);
        setenv("LD_PRELOAD", shim, 1);
        dup2(log[1], STDOUT_FILENO);
        dup2(log[1], STDERR_FILENO);
    } else {
        if (child > 0) { kill(child, SIGTERM); waitpid(child, NULL, 0); }
        close(event[1]);
        unsetenv("SS4S_WEBOS_OPUS71");
        unsetenv("SS4S_OPUS71_NOTIFY_FD");
    }
    close(log[1]);
    setenv("APPID", "com.ssz990220.moonlight.opus71", 1);
    argv[0] = binary;
    execv(binary, argv);
    return 1;
}
