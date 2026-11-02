#include <assert.h>
#include <stdio.h>
#include "opus71_sdk.h"

static int parse(const char *text, version_info_t *version) {
    FILE *file = tmpfile();
    assert(file);
    fputs(text, file); rewind(file);
    int result = opus71_sdk_read(file, version);
    fclose(file);
    return result;
}
int main(void) {
    version_info_t v = {0};
    assert(parse("10.3.1\n", &v) == 0 && v.major == 10 && v.minor == 3 && v.patch == 1);
    const char *bad[] = {"", "0.0.0", "-1.2.3", "10.3", "10.3.1junk", "10.3.1.4", "x10.3.1", "10.3.1000", "10.3.1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"};
    for (size_t i = 0; i < sizeof(bad) / sizeof(bad[0]); ++i) assert(parse(bad[i], &v) == -1);
    puts("PASS: explicit SDK metadata only; no guessed or zero version accepted");
    return 0;
}
