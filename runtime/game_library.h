// Shared contract between the Windows runtime and the player's locally built game DLL.
#pragma once
#include <stdint.h>

struct RtModule;
struct RtLayoutEntry;
struct RtFileHash;

#define GAME_LIBRARY_ABI 1
#define GAME_LIBRARY_MODULES 16
#define GAME_LIBRARY_PATCHES 64
#define GAME_LIBRARY_NAME L"engage_game.dll"
#define GAME_LIBRARY_ENTRY "engage_game_tables"

typedef struct RtPatchSet { const char *name, *env; int on; } RtPatchSet;
typedef struct GameLibrary {
    uint32_t abi, size;
    const char *compatibility;
    int game_id, game_version;
    const struct RtLayoutEntry *layout;
    int layout_count;
    const struct RtModule *modules;
    int module_count;
    const struct RtFileHash *hashes;
    int hash_count;
    const char *exefs, *romfs, *profile;
    const RtPatchSet *patches;
    int patch_count;
    uint64_t patch_page, romfs_size, romfs_files;
    const char *romfs_sha256, *index_sha256;
} GameLibrary;

#ifdef RT_GAME_LIBRARY
#ifdef __cplusplus
extern "C" {
#endif
const GameLibrary *rt_game_library(void);
#define rt_game_id (rt_game_library()->game_id)
#define rt_game_version (rt_game_library()->game_version)
#ifdef __cplusplus
}
#endif
#endif
