"""Windows Engage game DLL build and compatibility contract. No game inputs live here."""
import hashlib
import json
from pathlib import Path

DLL_NAME = 'engage_game.dll'
EXPORTS = ('rt_dispatch', 'rt_dispatch_resume', 'rt_guest_resume', 'rt_spin_gate', 'rt_svc', 'rt_brk', 'rt_udf',
           'rt_ticks', 'fnprof_hit', 'g_fnprof DATA', 'rt_patch_on DATA')


def compatibility_id(root, runtime):
    digest = hashlib.sha256()
    for path in [*sorted((root / 'recomp').glob('*.py')), root / 'recomp/patches-engage-v200.txt',
                 *(runtime / name for name in ('cpu.h', 'simd.h', 'dispatch.h', 'game_library.h', 'game_imports.h'))]:
        digest.update(path.name.encode() + b'\0' + path.read_bytes())
    digest.update('\n'.join(EXPORTS).encode())
    digest.update(b'windows-x86_64-v3;continuations;no-callee-saved-trust;game-library-1')
    return digest.hexdigest()


def private_glue(build, layout, linked, hashes, paths, version):
    text = build.module_glue(layout, linked, hashes, paths, version, runtime_version=False)
    return text + '''
#include "game_library.h"
#include "game_contract.h"
#include "romfs_config.h"
#if __has_include("patches.h")
#include "patches.h"
#endif
#ifndef RT_PATCH_COUNT
#define RT_PATCH_COUNT 0
#define RT_PATCH_PAGE 0
#endif
#if RT_PATCH_COUNT
#define X(i, n, e, d) {#n, e, d},
static const RtPatchSet game_patches[] = { RT_PATCH_SETS(X) };
#undef X
#else
#define game_patches NULL
#endif
__declspec(dllexport) const GameLibrary *engage_game_tables(void) {
    static RtModule modules[GAME_LIBRARY_MODULES];
    static GameLibrary game;
    int count = rt_linked_modules(modules, GAME_LIBRARY_MODULES);
    game = (GameLibrary){
        .abi = GAME_LIBRARY_ABI, .size = sizeof(GameLibrary), .compatibility = GAME_COMPATIBILITY_ID,
        .game_id = rt_game_id, .game_version = rt_game_version,
        .layout = rt_layout, .layout_count = rt_layout_count, .modules = modules, .module_count = count,
        .hashes = rt_exefs_sha256, .hash_count = rt_exefs_sha256_count,
        .exefs = rt_default_exefs, .romfs = rt_default_romfs, .profile = rt_default_profile,
        .patches = game_patches, .patch_count = RT_PATCH_COUNT, .patch_page = RT_PATCH_PAGE,
        .romfs_size = ROMFS_IMAGE_SIZE, .romfs_files = ROMFS_FILE_COUNT,
        .romfs_sha256 = ROMFS_IMAGE_SHA256, .index_sha256 = ROMFS_INDEX_SHA256,
    };
    return &game;
}
'''


def fingerprint(compatibility, private, mods, flags, headers=()):
    digest = hashlib.sha256((compatibility + private + '\n'.join(flags)).encode())
    for path in headers:
        digest.update(path.name.encode() + b'\0' + path.read_bytes())
    for mod, files in mods.items():
        for path in files:
            digest.update((mod + '/' + path.name).encode())
            with path.open('rb') as stream:
                while data := stream.read(1 << 20):
                    digest.update(data)
    return digest.hexdigest()


def reusable(out, key):
    try:
        saved = json.loads((out / 'game-library-build.json').read_text())
        with (out / DLL_NAME).open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        return saved.get('key') == key and saved.get('sha256') == digest
    except (OSError, ValueError):
        return False


def record(out, key, compatibility):
    with (out / DLL_NAME).open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    (out / 'game-library-build.json').write_text(json.dumps(
        {'key': key, 'compatibility': compatibility, 'sha256': digest}, indent=2) + '\n')


def check_runtime(exe, compatibility):
    info = json.loads(exe.with_suffix('.json').read_text())
    with exe.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if info.get('compatibility') != compatibility or info.get('sha256') != digest:
        raise ValueError('Bundled Engage runtime is damaged or incompatible with the game compiler')


def record_runtime(exe, compatibility):
    with exe.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    exe.with_suffix('.json').write_text(json.dumps(
        {'compatibility': compatibility, 'sha256': digest}, indent=2) + '\n')


def ninja_file(build, gen, out, mods, jobs, skip, reuse=False, runtime_only=False, runtime_exe=None):
    """Use the existing compile rules and object verification for two independently linked images."""
    text, objects, exe = build.ninja_file(gen, out, {} if reuse or runtime_only else mods, jobs, skip)
    lines = text.splitlines()
    # Replace the monolithic glue and link edge. The runtime reads its metadata from the DLL.
    glue_object = build.runtime_object(out, out / 'modules.c')
    objects['runtime'].remove(glue_object)
    lines = [line for line in lines if not line.startswith((
        'build ' + build.ninja_path(glue_object) + ':', 'build ' + build.ninja_path(exe) + ':',
        'build objects:', 'default '))]
    for i, line in enumerate(lines):
        if line.startswith('genflags = '):
            lines[i] += ' -include ' + build.cmd_path(build.RUNTIME / 'game_imports.h')
        if line.startswith('rtflags = '):
            lines[i] += ' -DRT_GAME_LIBRARY'
    dll = out / DLL_NAME
    definition = out / 'engage.def'
    if reuse and not runtime_only:
        lines.append(f'build {build.ninja_path(dll)}: phony')
    if not runtime_only and not reuse:
        import_lib = out / 'libengage-host.a'
        entry = out / 'game_private.c'
        entry_object = out / 'obj/game_private.o'
        # The entry also includes the generated headers, but must not use the runtime's metadata macros.
        lines += [f'build {build.ninja_path(entry_object)}: cc_gen {build.ninja_path(entry)}',
                  'rule host_imports',
                  f'  command = {build.cmd_arg((build.TOOLCHAIN_BIN / "llvm-dlltool.exe").as_posix())} '
                  '-m i386:x86-64 -d $in -l $out',
                  f'build {build.ninja_path(import_lib)}: host_imports {build.ninja_path(definition)}',
                  'rule game_dll',
                  '  command = $cc -fuse-ld=lld -shared -Wl,--exclude-all-symbols '
                  '-Wl,--image-base,0x180000000 @$out.rsp -o $out',
                  '  rspfile = $out.rsp', '  rspfile_content = $in_newline', '  description = DLL $out']
        generated = [o for name, group in objects.items() if name != 'runtime' for o in group]
        objects['game_entry'] = [entry_object]
        lines.append(f'build {build.ninja_path(dll)}: game_dll ' +
                     ' '.join(build.ninja_path(p) for p in [*generated, entry_object, import_lib]))
    if runtime_exe:
        runtime_objects = {build.ninja_path(p) for p in objects.pop('runtime')}
        lines = [line for line in lines if not any(line.startswith('build ' + p + ':') for p in runtime_objects)]
        artifact = dll
    else:
        lines.append(f'build {build.ninja_path(exe)}: link ' +
                     ' '.join(build.ninja_path(p) for p in [*objects['runtime'], definition]) +
                     ('' if runtime_only else ' || ' + build.ninja_path(dll)))
        artifact = exe
    every = [o for group in objects.values() for o in group]
    lines += ['build objects: phony ' + ' '.join(build.ninja_path(p) for p in every),
              f'default {build.ninja_path(artifact)}', '']
    return '\n'.join(lines), objects, artifact
