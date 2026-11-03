"""Frame-rate patch guards and startup selection, using synthetic inputs only."""
import io
import os
from pathlib import Path
import subprocess
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'recomp')]
import patches
from engage_setup.model import Form
from engage_setup.pipeline import Pipeline
from installer.events import Reporter


class FrameRateTest(unittest.TestCase):
    def table(self):
        return patches.load(ROOT / 'recomp/patches-engage-v200.txt', [('main', 0, 0x4000000)])

    def test_build_and_instruction_guards(self):
        table = self.table()
        mod = SimpleNamespace(base=0, nso=SimpleNamespace(build_id=table.builds['main']),
                              in_text=lambda a: True, word=lambda a: table.sites['main'][a][2])
        patches.check(table, mod, 'main')
        mod.nso.build_id = '00' * 32
        with self.assertRaisesRegex(patches.PatchError, 'build ID'):
            patches.check(table, mod, 'main')
        mod.nso.build_id = table.builds['main']
        mod.word = lambda a: 0
        with self.assertRaisesRegex(patches.PatchError, 'expects'):
            patches.check(table, mod, 'main')
        mod.in_text = lambda a: False
        with self.assertRaisesRegex(patches.PatchError, 'outside'):
            patches.check(table, mod, 'main')

    def test_setup_passes_engage_patch_table(self):
        with tempfile.TemporaryDirectory() as temp:
            pipeline = Pipeline(Form(dest=temp), SimpleNamespace(root=ROOT), Reporter(out=io.StringIO()))
            calls = []
            pipeline.python = lambda *args: calls.append(args)
            pipeline.state = {}
            (pipeline.extracted / 'ExeFS').mkdir(parents=True)
            pipeline.lift()
            args = calls[0]
            self.assertEqual(args[args.index('--patches') + 1], ROOT / 'recomp/patches-engage-v200.txt')

    def test_patch_preserves_the_vsync_count_contract(self):
        import unicorn as uc
        from unicorn import arm64_const as a
        _, replacements, original = next(iter(self.table().sites['main'].values()))
        mu = uc.Uc(uc.UC_ARCH_ARM64, uc.UC_MODE_ARM)
        mu.mem_map(0x1000, 0x1000)
        for word, patched in ((original, False), (replacements[0], True)):
            mu.mem_write(0x1000, struct.pack('<I', word))
            for count in (0, 1, 2, 3):
                mu.reg_write(a.UC_ARM64_REG_X0, count)
                mu.reg_write(a.UC_ARM64_REG_X19, 0xffffffffffffffff)
                mu.emu_start(0x1000, 0x1004)
                self.assertEqual(mu.reg_read(a.UC_ARM64_REG_X19), 1 if patched else count)

    def test_native_startup_selection_and_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            (work / 'layout.h').write_text('#define MOD_MAIN_BASE 0x7100000000ull\n')
            (work / 'test.c').write_text(r'''
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "host.h"
#include "cfg.h"
const int rt_game_id=1, rt_game_version=200;
uint64_t rt_guest_start_ns;
uint32_t rt_trace;
uint64_t kern_now_ns(void) { return 0; }
int plat_mem_read(uint64_t a,void *out,size_t n) { abort(); }
static const char *setting, *legacy;
static int enabled;
static unsigned version;
const char *cfg_get(const char *key) { return !strcmp(key,"TOTK_FPS_LIMIT") ? setting : legacy; }
unsigned cfg_version(void) { return version; }
int rt_patch_set(const char *name) { return !strcmp(name,"fps60") ? 0 : -1; }
int rt_patch_enabled(int set) { return set==0 && enabled; }
void rt_patch_switch(int set,int on) { assert(set==0); enabled=on; }
void rt_patch_disable(int set) { enabled=0; }
void *rt_patch_page(void) { abort(); }
double gfx_window_refresh_hz(void) { return 144; }
void rt_log(const char *fmt,...) {}
int main(int argc,char **argv) {
 assert(argc==4);
 setting=strcmp(argv[1],"unset") ? argv[1] : NULL;
 legacy=argv[2]; int expected=atoi(argv[3]);
 frame_step_init();
 assert(!frame_step_realtime());
 assert(enabled==(expected==60));
 assert(frame_step_limit_hz()==expected);
 assert(frame_step_cap_ns()==(uint64_t)(1e9/expected+0.5));
 setting=expected==60 ? "30" : "60"; version++;
 frame_step_cap_ns();
 assert(enabled==(expected==60) && frame_step_limit_hz()==expected);
}
''')
            cc = os.environ.get('CC', str(ROOT / 'toolchain/engage/llvm/bin/clang.exe'))
            exe = work / 'test.exe'
            result = subprocess.run([cc, '-O1', '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections',
                '-I', str(ROOT / 'runtime'), '-I', str(work), str(work / 'test.c'),
                str(ROOT / 'runtime/frame_rate.c'), '-o', str(exe)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for value, legacy, expected in [('30', '1', 30), ('60', '0', 60), ('144', '1', 60),
                    ('display', '1', 60), ('unset', '0', 30), ('unset', '1', 60), ('invalid', '1', 60)]:
                with self.subTest(value=value, legacy=legacy):
                    subprocess.run([str(exe), value, legacy, str(expected)], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
