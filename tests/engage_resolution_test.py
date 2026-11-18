"""Resolution startup validation and the guarded ARM64 stores, using synthetic inputs."""
import os
from pathlib import Path
import math
import re
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'recomp'))
import patches


def extra_kib(output, scale):
    """engage_heap_extra_kib (runtime/resolution.c) mirrored here: the C in the built test.exe is the authority,
    this computes what it must return for each case, independently. The tested inputs are plain integers and the
    listed invalid ones, which is what strtod and this mirror disagree on never. No DLSS in these cases: the
    stub's cfg_value answers TOTK_UPSCALER with the scale string, so the C computes shrink 1."""
    m = re.fullmatch(r'(\d+)x(\d+)', output)
    w, h = 1920, 1080
    if m and int(m[1]) >= 1280 and int(m[2]) >= 720:
        wn, hn = int(m[1]), int(m[2])
        ok = [(1280, 720), (1600, 900), (1920, 1080), (2560, 1440), (3200, 1800), (3840, 2160)]
        pw, ph = next(((a, b) for a, b in ok if (a, b) == (wn, hn)), (0, 0))
        if not pw:
            pw, ph = (1280, 720)   # the C loop keeps the last ok size at or below the window
            for a, b in ok:
                if a <= wn and b <= hn:
                    pw, ph = a, b
        w, h = pw, ph
    pct = 0
    if scale != 'game' and re.fullmatch(r'\d+', scale) and int(scale) > 0:
        pct = int(scale)
        pct = 25 if pct < 25 else 200 if pct > 200 else pct
    if pct <= 0:
        pct = 100   # the game's own scale stays within the draw size
    base = 1920 * 1080
    out = w * h
    scene = (w * pct // 100) * (h * pct // 100)
    if out <= base and scene <= base:
        return 0
    # 20 B per window pixel above 1080p (display images and UI), 32 B per scene pixel (targets and post chain)
    return math.ceil((20 * max(0, out - base) + 32 * max(0, scene - base)) / 1024)


class ResolutionTest(unittest.TestCase):
    def test_patch_stores(self):
        import unicorn as uc
        from unicorn import arm64_const as a
        table = patches.load(ROOT / 'recomp/patches-engage-v200.txt', [('main', 0, 0x7000000)])
        sites = table.for_module('main', 0)
        for off, (index, words) in sites.items():
            if table.sets[index][0] not in ('engage_output', 'engage_scene'):
                continue
            with self.subTest(site=hex(off)):
                mu = uc.Uc(uc.UC_ARCH_ARM64, uc.UC_MODE_ARM)
                mu.mem_map(off & ~4095, 4096)
                mu.mem_map(table.page, 4096)
                mu.mem_map(0x10000, 4096)
                mu.mem_write(table.page + 64, struct.pack('<IIf', 2560, 1440, .75))
                mu.mem_write(off, struct.pack('<' + 'I' * len(words), *words))
                mu.reg_write(a.UC_ARM64_REG_X0, 0x10000)
                mu.reg_write(a.UC_ARM64_REG_X19, 0x10000)
                mu.reg_write(a.UC_ARM64_REG_X29, 0x10800)
                mu.reg_write(a.UC_ARM64_REG_X20, 0x10400)
                mu.reg_write(a.UC_ARM64_REG_SP, 0x10f00)
                mu.emu_start(off, off + 4 * len(words))
                if table.sets[index][0] == 'engage_scene':
                    self.assertEqual(struct.unpack('<f', mu.mem_read(0x100e8, 4))[0], .75)
                elif off < 0xa00000:
                    offset = 0xc0 if off in (0x4afd8c, 0x4b0044, 0x4b0170) else 0xc4
                    self.assertEqual(struct.unpack('<I', mu.mem_read(0x10000 + offset, 4))[0],
                                     2560 if offset == 0xc0 else 1440)
                elif off == 0xa7cf48:
                    self.assertEqual(struct.unpack('<II', mu.mem_read(0x10800 - 0xd0, 8)), (2560, 1440))
                elif off == 0xa67090:
                    self.assertEqual(struct.unpack('<I', mu.mem_read(0x10400, 4))[0], 2560)
                    self.assertEqual(struct.unpack('<I', mu.mem_read(0x10000, 4))[0], 1440)
                else:
                    reg, expected = {0xa7cff0: (a.UC_ARM64_REG_X21, 1440),
                                     0xa7cff8: (a.UC_ARM64_REG_X1, 2560),
                                     0xa7d08c: (a.UC_ARM64_REG_X1, 2560),
                                     0xa7d26c: (a.UC_ARM64_REG_X1, 2560),
                                     0xa7d270: (a.UC_ARM64_REG_X2, 1440),
                                     0xa65e70: (a.UC_ARM64_REG_X3, 1440),
                                     0xa65e7c: (a.UC_ARM64_REG_X2, 2560)}[off]
                    self.assertEqual(mu.reg_read(reg), expected)

    def test_native_startup(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            # Engage must never enter TotK's compressed HeapDef path; abort if it does.
            (work / 'zstd.h').write_text(r'''
#include <stdlib.h>
#define ZSTD_CONTENTSIZE_UNKNOWN (~0ull)
#define ZSTD_CONTENTSIZE_ERROR (~1ull)
#define ZSTD_getDictID_fromFrame(...) (abort(), 0u)
#define ZSTD_getFrameContentSize(...) (abort(), 0ull)
#define ZSTD_decompress(...) (abort(), (size_t)0)
#define ZSTD_isError(...) (abort(), 0u)
#define ZSTD_compressBound(...) (abort(), (size_t)0)
#define ZSTD_compress(...) (abort(), (size_t)0)
''')
            (work / 'test.c').write_text(r'''
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "host.h"
const int rt_game_id=1, rt_game_version=200;
static const char *output, *scale;
static unsigned char page[4096];
static int enabled[2];
const char *cfg_value(const char *key) { return !strcmp(key,"TOTK_WINDOW_SIZE") ? output : scale; }
int rt_patch_set(const char *name) { return !strcmp(name,"engage_output") ? 0 : !strcmp(name,"engage_scene") ? 1 : -1; }
void rt_patch_switch(int set,int on) { assert(set>=0 && set<2); enabled[set]=on; }
void *rt_patch_page(void) { return page; }
void rt_log(const char *fmt,...) {}
int mem_pool_grow(uint64_t extra) { (void)extra; return 0; }   // the boot sizing already covered it in every case
int mem_pool_pinned(void) { return 0; }   // no TOTK_APP_POOL in these cases: the cap follows the settings
void oe_push_message(unsigned message) {}
void ov_operation_mode_flip(void) {}
int ov_op_flipped(void) { return 0; }
int ov_operation_mode_flip_ended(void) { return 0; }
int gfx_window_monitor_size(int *w, int *h) { *w = 0; *h = 0; return 0; }
void fs_init(void) { abort(); }
int cfg_int(const char *key) { abort(); }
int main(int argc,char **argv) {
 assert(argc==7); output=argv[1]; scale=argv[2];
 res_init();
 unsigned w,h; float k;
 memcpy(&w,page+64,4); memcpy(&h,page+68,4); memcpy(&k,page+72,4);
 assert(w==(unsigned)atoi(argv[3]) && h==w*9/16);
 // engage_output stays on at every size: its sites feed a store Unity makes while it sets up its display, so a size
 // switched off here used to leave the last written value behind (a return to a larger size kept drawing 720p).
 assert(enabled[0]==1);
 assert(enabled[1]==atoi(argv[4]));
 assert(k==(float)atof(argv[5]));
 // the guest pool extra (engage_heap_extra_kib): above Switch's retail pool exactly when the session draws or
 // scales above 1920x1080
 assert(res_heap_extra_kib()==strtoull(argv[6],NULL,10));
}
''')
            cc = os.environ.get('CC', str(ROOT / 'toolchain/engage/llvm/bin/clang.exe'))
            exe = work / 'test.exe'
            result = subprocess.run([cc, '-O1', '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections',
                '-I', str(ROOT / 'runtime'), '-I', str(work),
                str(work / 'test.c'), str(ROOT / 'runtime/resolution.c'),
                '-lm', '-o', str(exe)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            cases = [('1280x720', '50', 1280, 1, .5), ('1600x900', '75', 1600, 1, .75),
                     ('1920x1080', '100', 1920, 1, 1), ('2560x1440', '150', 2560, 1, 1.5),
                     ('3200x1800', '100', 3200, 1, 1), ('3840x2160', '100', 3840, 1, 1),
                     ('1920x1080', 'game', 1920, 0, 1), ('3440x1440', 'game', 2560, 0, 1),
                     ('1280x720junk', '75', 1920, 1, .75),
                     # any typed percentage inside 25..200 now works, clamped to the limits
                     ('1920x1080', '25', 1920, 1, .25), ('1920x1080', '133', 1920, 1, 1.33),
                     ('1920x1080', '200', 1920, 1, 2), ('1920x1080', '10', 1920, 1, .25),
                     ('1920x1080', '999', 1920, 1, 2)]
            cases += [('1920x1080', value, 1920, 0, 1)
                      for value in ('nan', 'inf', '0', 'bad', '75%')]
            for case in cases:
                with self.subTest(case=case):
                    subprocess.run([str(exe), *map(str, (*case, extra_kib(case[0], case[1])))],
                                   check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
