// Filesystem adapter for testing the real C mod manager without game inputs.
#include <filesystem>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
extern "C" {
#include "mods.h"
#include "platform/platform.h"
}
namespace fs = std::filesystem;
static std::string executable, setting;
extern "C" {
void rt_fatal(const char *, ...) { std::abort(); }
void rt_log(const char *, ...) {}
const char *cfg_get(const char *) { return setting.c_str(); }
int cfg_from_env(const char *) { return 0; }
void cfg_set(const char *, const char *value) { setting = value; }
void plat_once(PlatOnce *o, void (*fn)(void *), void *p) { if (!o->state) { o->state = 1; fn(p); } }
int plat_exe_path(char *out, size_t cap) { return std::snprintf(out, cap, "%s", executable.c_str()); }
int plat_fs_kind(const char *path) {
    std::error_code ec;
    auto s = fs::symlink_status(fs::u8path(path), ec);
    if (ec) return PLAT_FS_MISSING;
    if (fs::is_symlink(s)) return PLAT_FS_LINK;
    if (fs::is_directory(s)) return PLAT_FS_DIR;
    return fs::is_regular_file(s) ? PLAT_FS_FILE : PLAT_FS_MISSING;
}
int plat_fs_mkdir(const char *p) { std::error_code ec; return fs::create_directory(fs::u8path(p), ec) ? PLAT_FS_OK : PLAT_FS_ERROR; }
int plat_fs_list(const char *p, int (*cb)(const char *, int, uint64_t, void *), void *ctx) {
    std::error_code ec;
    fs::directory_iterator it(fs::u8path(p), ec), end;
    if (ec) return PLAT_FS_ERROR;
    for (; it != end; it.increment(ec)) {
        if (ec) return PLAT_FS_ERROR;
        auto path = it->path().u8string(), name = it->path().filename().u8string();
        if (!cb(name.c_str(), plat_fs_kind(path.c_str()), 0, ctx)) break;
    }
    return ec ? PLAT_FS_ERROR : PLAT_FS_OK;
}
}
static int apply(const char *relative, const char *, void *) {
    std::printf("file\t%s\n", relative);
    return MOD_FILE_REPLACED;
}
int main(int argc, char **argv) {
    executable = std::string(argv[1]) + "/test.exe";
    if (argc > 2) setting = argv[2];
    mods_each_file(apply, nullptr);
    if (argc > 3) mods_set_enabled(std::atoi(argv[3]), 0);
    for (int i = 0; i < mods_count(); i++) {
        ModInfo m; mods_get(i, &m);
        std::printf("mod\t%s\t%d\t%d\t%d\t%d\t%zu\t%zu\t%zu\t%s\n", m.name,
                    m.supported, m.active, m.enabled, m.code, m.files, m.replaced, m.shadowed, m.problem);
    }
    std::printf("setting\t%s\nrestart\t%d\nproblem\t%s\n", setting.c_str(), mods_restart_required(), mods_problem());
}
