#pragma once
#include <stdio.h>
#include <string.h>
#include "os_info.h"

/* App-owned installation metadata, not a forced or guessed OS version. */
static inline int opus71_sdk_read(FILE *file, version_info_t *version) {
    char line[32];
    if (!file || !fgets(line, sizeof(line), file)) return -1;
    size_t n = strcspn(line, "\r\n");
    if (!n || n == sizeof(line) - 1) return -1;
    line[n] = 0;
    int major, minor, patch;
    char extra;
    if (sscanf(line, "%d.%d.%d%c", &major, &minor, &patch, &extra) != 3 ||
        major <= 0 || major > 99 || minor < 0 || minor > 999 || patch < 0 || patch > 999) return -1;
    for (size_t i = 0; i < n; ++i) if ((line[i] < '0' || line[i] > '9') && line[i] != '.') return -1;
    *version = (version_info_t){major, minor, patch};
    return 0;
}

int opus71_sdk_fallback(os_info_t *info);
