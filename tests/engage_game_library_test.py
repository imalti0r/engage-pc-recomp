"""Synthetic Windows DLL contracts and cache checks; no game files are used."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import game_library


class LibraryCacheTest(unittest.TestCase):
    def test_romfs_identity_change_invalidates_cached_game_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            header = Path(temp) / 'romfs_config.h'
            header.write_text('original game image identity')
            before = game_library.fingerprint('contract', 'private', {}, [], [header])
            header.write_text('changed game image identity')
            self.assertNotEqual(before, game_library.fingerprint('contract', 'private', {}, [], [header]))

    def test_runtime_fixes_keep_contract_but_cpu_or_patch_changes_invalidate_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = root / 'runtime'
            runtime.mkdir()
            (root / 'recomp').mkdir()
            (root / 'recomp/gen.py').write_text('generator')
            (root / 'recomp/patches-engage-v200.txt').write_text('patches')
            for name in ('cpu.h', 'simd.h', 'dispatch.h', 'game_library.h', 'game_imports.h'):
                (runtime / name).write_text(name)
            before = game_library.compatibility_id(root, runtime)
            (runtime / 'vk_backend.c').write_text('runtime fix')
            self.assertEqual(before, game_library.compatibility_id(root, runtime))
            (runtime / 'cpu.h').write_text('changed CPU interface')
            self.assertNotEqual(before, game_library.compatibility_id(root, runtime))
            (runtime / 'cpu.h').write_text('cpu.h')
            self.assertEqual(before, game_library.compatibility_id(root, runtime))
            (root / 'recomp/patches-engage-v200.txt').write_text('new game patches')
            self.assertNotEqual(before, game_library.compatibility_id(root, runtime))

    def test_dll_reuse_checks_both_input_identity_and_file_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            dll = out / game_library.DLL_NAME
            dll.write_bytes(b'synthetic DLL')
            game_library.record(out, 'inputs', 'contract')
            self.assertTrue(game_library.reusable(out, 'inputs'))
            self.assertFalse(game_library.reusable(out, 'new inputs'))
            dll.write_bytes(b'changed DLL')
            self.assertFalse(game_library.reusable(out, 'inputs'))

    def test_prebuilt_runtime_is_bound_to_contract_and_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            exe = Path(temp) / 'engage.exe'
            exe.write_bytes(b'synthetic runtime')
            game_library.record_runtime(exe, 'contract')
            game_library.check_runtime(exe, 'contract')
            with self.assertRaises(ValueError):
                game_library.check_runtime(exe, 'different contract')
            exe.write_bytes(b'tampered runtime')
            with self.assertRaises(ValueError):
                game_library.check_runtime(exe, 'contract')


@unittest.skipUnless(os.name == 'nt', 'Windows loader contract')
class NativeLibraryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = ROOT / 'toolchain/engage/llvm/bin/clang.exe'
        if not cls.compiler.is_file():
            raise unittest.SkipTest('local pinned Clang is not installed')

    def compile(self, *args):
        subprocess.run([str(self.compiler), *map(str, args)], check=True, capture_output=True, text=True)

    def fixture(self, folder, change=''):
        source = folder / 'fixture.c'
        source.write_text('''
#include "host.h"
#include "game_contract.h"
static void fn(Cpu *c) { (void)c; }
static const uint64_t addresses[] = {0x7000000000ull};
static const GuestFn functions[] = {fn};
static const RtLayoutEntry layout[] = {{"main",1,1},{"subsdk0",2,1},{"sdk",3,1}};
static const RtModule modules[] = {
    {"main",1,1,addresses,functions,1},{"subsdk0",2,1,addresses,functions,1},
    {"sdk",3,1,addresses,functions,1}};
static const RtFileHash hashes[] = {{"main","x"},{"subsdk0","x"},{"sdk","x"}};
static GameLibrary game = {
    .abi=GAME_LIBRARY_ABI,.size=sizeof(GameLibrary),.compatibility=GAME_COMPATIBILITY_ID,
    .game_id=1,.game_version=200,.layout=layout,.layout_count=3,.modules=modules,.module_count=3,
    .hashes=hashes,.hash_count=3,.exefs="exefs",.romfs="romfs",.profile="profile",
    .romfs_sha256="",.index_sha256=""};
__declspec(dllexport) const GameLibrary *engage_game_tables(void) {
''' + change + '\nreturn &game;\n}\n')
        self.compile('-shared', '-I', ROOT / 'runtime', '-I', folder, source, '-o', folder / 'engage_game.dll')

    def test_missing_valid_incompatible_and_malformed_libraries(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / 'game_contract.h').write_text('#define GAME_COMPATIBILITY_ID "fixture"\n'
                                                  '#define GAME_RUNTIME_VERSION "test"\n')
            main = folder / 'probe.c'
            main.write_text('#include "host.h"\nint main(void) { return rt_game_library()->game_version != 200; }\n')
            exe = folder / 'probe.exe'
            self.compile('-D_WIN32_WINNT=0x0A00', '-DRT_GAME_LIBRARY', '-I', ROOT / 'runtime', '-I', folder,
                         ROOT / 'runtime/game_library.c', main, '-o', exe)
            cases = [(None, 'cannot load'), ('', 'loaded engage_game.dll'),
                     ('game.abi++;', 'incompatible'), ('game.compatibility="different";', 'incompatible'),
                     ('game.module_count=17;', 'invalid'), ('game.modules=NULL;', 'invalid')]
            for change, message in cases:
                with self.subTest(change=change):
                    if change is not None:
                        self.fixture(folder, change)
                    result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=15)
                    self.assertEqual(result.returncode, 0 if change == '' else 70, result.stderr)
                    self.assertIn(message, result.stderr)

    def test_generated_data_uses_the_runtime_import_table(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            definition = folder / 'host.def'
            definition.write_text('LIBRARY engage.exe\nEXPORTS\ng_fnprof DATA\nrt_patch_on DATA\n')
            subprocess.run([str(self.compiler.with_name('llvm-dlltool.exe')), '-m', 'i386:x86-64',
                            '-d', str(definition), '-l', str(folder / 'host.a')], check=True, capture_output=True)
            dll = folder / 'data.c'
            dll.write_text('#include "game_imports.h"\n#include "cpu.h"\n'
                           'extern RT_GAME_DATA uint8_t rt_patch_on[];\n'
                           '__declspec(dllexport) int touch(void) {\n'
                           'int old=g_fnprof+rt_patch_on[0]; g_fnprof=9;rt_patch_on[0]=8;return old;}\n')
            self.compile('-shared', '-I', ROOT / 'runtime', dll, folder / 'host.a', '-o', folder / 'data.dll')
            main = folder / 'data_main.c'
            main.write_text('#include <windows.h>\nvolatile int g_fnprof=3;unsigned char rt_patch_on[64]={4};\n'
                            'int main(void) { HMODULE d=LoadLibraryW(L"data.dll");if(!d)return 1;\n'
                            'int (*f)(void)=(void*)GetProcAddress(d,"touch");\n'
                            'return !f || f()!=7 || g_fnprof!=9 || rt_patch_on[0]!=8; }\n')
            exe = folder / 'engage.exe'
            self.compile(main, definition, '-o', exe)
            result = subprocess.run([str(exe)], cwd=folder, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
