// Verify that selected mod files reach the game's read-only filesystem byte for byte.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "host.h"
#include "fs.h"
#include "mods.h"

int probe_mods(void) {
    if (!RT_ENGAGE) return 2;
    fs_init();
    if (romfs_mount("rom")) return 1;
    unsigned char *guest = malloc(1u << 20), *host = malloc(1u << 20);
    if (!guest || !host) rt_fatal("mods probe: out of memory");
    int bad = 0;
    for (size_t k = 0; k < romfs_overlay_count(); k++) {
        const char *file;
        uint64_t size;
        int added;
        const char *name = romfs_overlay(k, &file, &size, &added);
        char path[4096];
        snprintf(path, sizeof path, "rom:/%s", name);
        uint64_t h = 0, rejected = 0;
        int64_t actual = -1;
        FILE *f = fopen(file, "rb");
        int ok = f && !romfs_open(&h, path, FS_OPEN_READ) && !romfs_size(&actual, h) && actual == (int64_t)size;
        for (uint64_t offset = 0; ok && offset < size;) {
            size_t n = size - offset > (1u << 20) ? (1u << 20) : (size_t)(size - offset);
            uint64_t got = 0;
            ok = fread(host, 1, n, f) == n && !romfs_read(&got, h, (int64_t)offset, guest, n) &&
                 got == n && !memcmp(guest, host, n);
            offset += n;
        }
        uint64_t got = 1;
        if (ok) ok = !romfs_read(&got, h, (int64_t)size, guest, 1) && !got &&
                     romfs_open(&rejected, path, FS_OPEN_WRITE) == FS_R_UNSUPPORTED_OPEN;
        if (h) romfs_close(h);
        if (f) fclose(f);
        printf("mods-probe: %s %s (%llu bytes, %s)\n", ok ? "passed" : "FAIL", name,
               (unsigned long long)size, added ? "added" : "replaced");
        if (!ok) bad++;
    }
    for (int i = 0; i < mods_count(); i++) {
        ModInfo m; mods_get(i, &m);
        printf("mods-probe: %s: active=%d replaced=%zu added=%zu overridden=%zu %s\n",
               m.name, m.active, m.replaced, m.added, m.shadowed, m.problem);
    }
    free(guest); free(host);
    printf("mods-probe: %s (%zu overlays, %d failures)\n", bad ? "FAILED" : "passed", romfs_overlay_count(), bad);
    return bad ? 1 : 0;
}
