"""Resolution startup validation and the guarded ARM64 stores, using synthetic inputs."""
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'recomp'))
import patches


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
const char *cfg_value(const char *key) { return !strcmp(key,"TOTK_OUTPUT_RES") ? output : scale; }
int rt_patch_set(const char *name) { return !strcmp(name,"engage_output") ? 0 : !strcmp(name,"engage_scene") ? 1 : -1; }
void rt_patch_switch(int set,int on) { assert(set>=0 && set<2); enabled[set]=on; }
void *rt_patch_page(void) { return page; }
void rt_log(const char *fmt,...) {}
void fs_init(void) { abort(); }
int cfg_int(const char *key) { abort(); }
int main(int argc,char **argv) {
 assert(argc==6); output=argv[1]; scale=argv[2];
 res_init();
 unsigned w,h; float k;
 memcpy(&w,page+64,4); memcpy(&h,page+68,4); memcpy(&k,page+72,4);
 assert(w==(unsigned)atoi(argv[3]) && h==w*9/16);
 assert(enabled[0]==(w!=1920));
 assert(enabled[1]==atoi(argv[4]));
 assert(k==(float)atof(argv[5]));
 assert(res_heap_extra_kib()==0);
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
                     ('1920x1080', 'game', 1920, 0, 1), ('3440x1440', 'game', 1920, 0, 1),
                     ('1280x720junk', '75', 1920, 1, .75)]
            cases += [('1920x1080', value, 1920, 0, 1)
                      for value in ('nan', 'inf', '0', '49', '151', '200', 'bad', '75%')]
            for case in cases:
                with self.subTest(case=case):
                    subprocess.run([str(exe), *map(str, case)], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
