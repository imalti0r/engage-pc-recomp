#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cfg.h"
#include "host.h"
#include "mods.h"
#include "platform/platform.h"
#include "romfs_path.h"

#define MOD_PATH 2100
#define TITLE "0100A6301214E000"

typedef struct {
    char *name, *path, *token;
    char problem[192];
    int enabled, active, supported, code;
    size_t files, shadowed, replaced, added;
} Mod;
typedef struct { char *relative, *host; int mod; } ModFile;
static Mod *list;
static int count;
static ModFile *files;
static size_t nfiles;
static char directory[MOD_PATH], problem[192];

static void *grow(void *p, size_t n) {
    void *next = realloc(p, n);
    if (!next) rt_fatal("mods: out of memory");
    return next;
}
static char *copy(const char *s) {
    char *p = strdup(s);
    if (!p) rt_fatal("mods: out of memory");
    return p;
}
static int join(char *out, size_t n, const char *a, const char *b) {
    int len = snprintf(out, n, "%s/%s", a, b);
    return len >= 0 && len < (int)n;
}

// Hex folder names are lossless settings IDs, including Unicode, commas and punctuation.
static char *token(const char *name) {
    size_t n = strlen(name);
    char *out = grow(NULL, 2 * n + 1);
    for (size_t i = 0; i < n; i++) snprintf(out + 2 * i, 3, "%02x", (unsigned char)name[i]);
    return out;
}
static int disabled(const char *id) {
    const char *value = cfg_get("TOTK_MODS_DISABLED");
    if (!value) return 0;
    size_t n = strlen(id);
    for (const char *p = value; *p;) {
        size_t k = strcspn(p, ",");
        if (k == n && !strncmp(p, id, n)) return 1;
        p += k;
        if (*p) p++;
    }
    return 0;
}

static int mod_order(const void *a, const void *b) {
    const Mod *x = a, *y = b;
    int n = strcasecmp(x->name, y->name);
    return n ? n : strcmp(x->name, y->name);
}
static int file_order(const void *a, const void *b) {
    const ModFile *x = a, *y = b;
    int n = strcmp(x->relative, y->relative);
    return n ? n : (x->mod > y->mod) - (x->mod < y->mod);
}

static int discover(const char *name, int kind, uint64_t size, void *ctx) {
    (void)size; (void)ctx;
    if (kind != PLAT_FS_DIR && kind != PLAT_FS_LINK) return 1;
    if (!romfs_path_valid_relative(name) || strchr(name, '/') || strchr(name, ':')) return 1;
    char path[MOD_PATH];
    if (!join(path, sizeof path, directory, name)) {
        snprintf(problem, sizeof problem, "A mod folder path is too long. Move the install to a shorter path.");
        return 1;
    }
    list = grow(list, (size_t)(count + 1) * sizeof *list);
    Mod *m = &list[count++];
    *m = (Mod){.name = copy(name), .path = copy(path), .token = token(name)};
    if (kind == PLAT_FS_LINK) snprintf(m->problem, sizeof m->problem, "Linked mod folders are not supported. Extract into a regular folder.");
    return 1;
}

// Check every wrapper component so Atmosphere paths cannot traverse a junction or symlink.
static int regular_directory(const char *base, const char *relative) {
    char path[MOD_PATH];
    if (!join(path, sizeof path, base, relative)) return 0;
    size_t start = strlen(base) + 1;
    for (char *p = path + start;; p++) {
        if (*p && *p != '/') continue;
        char c = *p; *p = 0;
        int kind = plat_fs_kind(path);
        *p = c;
        if (kind != PLAT_FS_DIR) return 0;
        if (!c) return 1;
    }
}

typedef struct { int mod; const char *root, *dir; } Walk;
static void walk(int mod, const char *root, const char *dir);
static int scan(const char *name, int kind, uint64_t size, void *opaque) {
    (void)size;
    Walk *w = opaque;
    Mod *m = &list[w->mod];
    char path[MOD_PATH];
    if (!romfs_path_valid_relative(name) || strchr(name, '/') || strchr(name, ':') ||
        !join(path, sizeof path, w->dir, name)) {
        snprintf(m->problem, sizeof m->problem, "A mod file path is invalid or too long.");
        return 0;
    }
    if (kind == PLAT_FS_LINK) {
        snprintf(m->problem, sizeof m->problem, "Linked files/folders are not supported. Extract a regular copy of this mod.");
        return 0;
    }
    if (kind == PLAT_FS_DIR) walk(w->mod, w->root, path);
    else if (kind == PLAT_FS_FILE) {
        m->files++;
        if (m->active) {
            files = grow(files, (nfiles + 1) * sizeof *files);
            files[nfiles++] = (ModFile){copy(path + strlen(w->root) + 1), copy(path), w->mod};
        }
    }
    return !*m->problem;
}
static void walk(int mod, const char *root, const char *dir) {
    Walk w = {mod, root, dir};
    if (plat_fs_list(dir, scan, &w) != PLAT_FS_OK && !*list[mod].problem)
        snprintf(list[mod].problem, sizeof list[mod].problem, "The mod folder could not be read. Check its permissions.");
}

static void initialize(void *unused) {
    (void)unused;
    char exe[MOD_PATH];
    int n = plat_exe_path(exe, sizeof exe);
    char *cut = n && n < sizeof exe ? plat_last_sep(exe) : NULL;
    if (!cut) { snprintf(problem, sizeof problem, "Could not find the game folder."); return; }
    *cut = 0;
    if (!join(directory, sizeof directory, exe, "mods")) {
        snprintf(problem, sizeof problem, "The game folder path is too long."); return;
    }
    int kind = plat_fs_kind(directory);
    if (kind == PLAT_FS_MISSING) {
        if (plat_fs_mkdir(directory) == PLAT_FS_OK) kind = PLAT_FS_DIR;
    }
    if (kind != PLAT_FS_DIR) {
        snprintf(problem, sizeof problem, "The mods folder must be a readable, regular directory."); return;
    }
    if (plat_fs_list(directory, discover, NULL) != PLAT_FS_OK) {
        snprintf(problem, sizeof problem, "Could not read the mods folder."); return;
    }
    if (count) qsort(list, (size_t)count, sizeof *list, mod_order);
    static const char *const wrappers[] = {"", TITLE "/", "contents/" TITLE "/", "atmosphere/contents/" TITLE "/"};
    for (int i = 0; i < count; i++) {
        Mod *m = &list[i];
        if (*m->problem) continue;
        char root[MOD_PATH] = {0};
        for (unsigned j = 0; j < sizeof wrappers / sizeof *wrappers; j++) {
            char rel[128];
            snprintf(rel, sizeof rel, "%sexefs", wrappers[j]);
            if (regular_directory(m->path, rel)) m->code = 1;
            snprintf(rel, sizeof rel, "%sromfs", wrappers[j]);
            if (!*root && regular_directory(m->path, rel)) join(root, sizeof root, m->path, rel);
        }
        if (!*root) {
            snprintf(m->problem, sizeof m->problem, "%s", m->code ? "Code-only mod: executable patches are not supported." :
                     "No romfs folder found. Extract the mod into mods/<name>/romfs/.");
            continue;
        }
        m->supported = 1;
        m->enabled = m->active = !disabled(m->token);
        size_t first = nfiles;
        walk(i, root, root);
        if (*m->problem) {
            m->supported = m->enabled = m->active = 0;
            while (nfiles > first) { nfiles--; free(files[nfiles].relative); free(files[nfiles].host); }
        }
    }
    if (nfiles) qsort(files, nfiles, sizeof *files, file_order);
    rt_log("mods: %d folders, %zu candidate RomFS files from enabled mods", count, nfiles);
}
static void init(void) {
    static PlatOnce once = PLAT_ONCE_INIT;
    plat_once(&once, initialize, NULL);
}

int mods_count(void) { init(); return count; }
const char *mods_directory(void) { init(); return directory; }
const char *mods_problem(void) { init(); return problem; }
int mods_get(int i, ModInfo *out) {
    init();
    if (!out || i < 0 || i >= count) return 0;
    Mod *m = &list[i];
    *out = (ModInfo){m->name, m->problem, m->enabled, m->active, m->supported, m->code,
                    m->files, m->shadowed, m->replaced, m->added};
    return 1;
}
void mods_set_enabled(int i, int enabled) {
    init();
    if (i < 0 || i >= count || !list[i].supported || cfg_from_env("TOTK_MODS_DISABLED")) return;
    list[i].enabled = enabled != 0;
    const char *old = cfg_get("TOTK_MODS_DISABLED");
    size_t cap = (old ? strlen(old) : 0) + strlen(list[i].token) + 2, n = 0;
    char *value = grow(NULL, cap);
    value[0] = 0;
    for (const char *p = old ? old : ""; *p;) {
        size_t len = strcspn(p, ",");
        if (len && !(len == strlen(list[i].token) && !strncmp(p, list[i].token, len))) {
            if (n) value[n++] = ',';
            memcpy(value + n, p, len); n += len;
        }
        p += len;
        if (*p) p++;
    }
    if (!list[i].enabled) {
        if (n) value[n++] = ',';
        size_t len = strlen(list[i].token);
        memcpy(value + n, list[i].token, len); n += len;
    }
    value[n] = 0;
    cfg_set("TOTK_MODS_DISABLED", value);
    free(value);
}
int mods_restart_required(void) {
    init();
    for (int i = 0; i < count; i++) if (list[i].enabled != list[i].active) return 1;
    return 0;
}
void mods_each_file(int (*apply)(const char *, const char *, void *), void *ctx) {
    init();
    const char *previous = NULL;
    for (size_t k = 0; k < nfiles; k++) {
        ModFile *f = &files[k];
        Mod *m = &list[f->mod];
        if (previous && !strcmp(previous, f->relative)) { m->shadowed++; continue; }
        previous = f->relative;
        int result = apply(f->relative, f->host, ctx);
        if (result == MOD_FILE_REPLACED) m->replaced++;
        else if (result == MOD_FILE_ADDED) m->added++;
    }
}
