// Emulator-style RomFS mods. File selection is frozen at startup; UI choices apply after restart.
#pragma once
#include <stddef.h>

typedef struct ModInfo {
    const char *name, *problem;
    int enabled, active, supported, code;
    size_t files, shadowed, replaced, added;
} ModInfo;

#ifdef __cplusplus
extern "C" {
#endif
int mods_count(void);
int mods_get(int index, ModInfo *out);
void mods_set_enabled(int index, int enabled);
int mods_restart_required(void);
const char *mods_directory(void);
const char *mods_problem(void);
int probe_mods(void);
enum { MOD_FILE_SKIPPED, MOD_FILE_REPLACED, MOD_FILE_ADDED };
void mods_each_file(int (*apply)(const char *relative, const char *host, void *ctx), void *ctx);
#ifdef __cplusplus
}
#endif
