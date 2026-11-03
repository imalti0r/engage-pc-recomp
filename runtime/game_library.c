#ifdef RT_GAME_LIBRARY
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "host.h"
#include "game_contract.h"

const char rt_port_version[] = GAME_RUNTIME_VERSION;
static const GameLibrary *library;

static void library_error(const char *why) {
    fprintf(stderr, "Engage game library: %s. Run Engage Setup to rebuild the game DLL.\n", why);
    fflush(stderr);
    _Exit(70);
}

const GameLibrary *rt_game_library(void) {
    if (library) return library;
    // Called on the main thread before guest memory, threads or settings depend on the metadata.
    wchar_t path[32768];
    DWORD n = GetModuleFileNameW(NULL, path, sizeof path / sizeof *path);
    if (!n || n >= sizeof path / sizeof *path) library_error("cannot locate the runtime");
    wchar_t *cut = wcsrchr(path, L'\\');
    if (!cut || cut - path + 1 + sizeof GAME_LIBRARY_NAME / sizeof(wchar_t) > sizeof path / sizeof *path)
        library_error("runtime path is too long");
    wcscpy(cut + 1, GAME_LIBRARY_NAME);
    HMODULE dll = LoadLibraryExW(path, NULL, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    if (!dll) {
        char why[160];
        snprintf(why, sizeof why, "cannot load engage_game.dll next to engage.exe (Windows error %lu)", GetLastError());
        library_error(why);
    }
    const GameLibrary *(*entry)(void) = (void *)GetProcAddress(dll, GAME_LIBRARY_ENTRY);
    if (!entry) library_error("engage_game.dll has no game table entry");
    const GameLibrary *g = entry();
    if (!g || g->abi != GAME_LIBRARY_ABI || g->size != sizeof *g || !g->compatibility ||
        strcmp(g->compatibility, GAME_COMPATIBILITY_ID)) library_error("runtime and game DLL are incompatible");
    if (g->game_id != 1 || g->game_version != 200 || !g->layout || !g->modules ||
        g->layout_count != 3 || g->module_count != 3 || !g->hashes || g->hash_count < 3 || g->hash_count > 16 ||
        !g->exefs || !g->romfs || !g->profile || g->patch_count < 0 || g->patch_count > GAME_LIBRARY_PATCHES ||
        (g->patch_count && !g->patches) || !g->romfs_sha256 || !g->index_sha256)
        library_error("invalid game DLL metadata");
    static const char *names[] = {"main", "subsdk0", "sdk"};
    for (int i = 0; i < g->module_count; i++) {
        const RtModule *m = &g->modules[i];
        const RtLayoutEntry *l = &g->layout[i];
        if (!m->name || !l->name || strcmp(m->name, names[i]) || strcmp(l->name, names[i]) ||
            m->base != l->base || m->size != l->size || !m->size || !m->count || !m->addrs || !m->fns)
            library_error("invalid game DLL module table");
    }
    library = g;   // The DLL stays loaded for the process lifetime; every dispatch pointer belongs to it.
    fprintf(stderr, "game-library: loaded engage_game.dll (ABI %u, compatibility %.12s)\n", g->abi, g->compatibility);
    return library;
}

int rt_linked_modules(RtModule *out, int max) {
    const GameLibrary *g = rt_game_library();
    int n = max < g->module_count ? max : g->module_count;
    if (n > 0) memcpy(out, g->modules, (size_t)n * sizeof *out);
    return n;
}
#endif
