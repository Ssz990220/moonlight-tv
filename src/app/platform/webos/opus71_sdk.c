#include <stdlib.h>
#include <string.h>
#include "opus71_sdk.h"
#include "util/path.h"

int opus71_sdk_fallback(os_info_t *info) {
    bool persistent;
    char *folder = path_pref(&persistent);
    char *path = path_join(folder, "device-sdk-version");
    FILE *file = fopen(path, "r");
    free(path);
    free(folder);
    if (!file) return -1;
    version_info_t version;
    int result = opus71_sdk_read(file, &version);
    fclose(file);
    if (result == 0) {
        info->version = version;
        if (!info->name) info->name = strdup("webOS");
    }
    return result;
}
