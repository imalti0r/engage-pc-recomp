"""The keyboard-and-mouse prompt icons: geometry, generated header and drawn cells.

The rectangles are the game's own sprite layout (plain numbers, no artwork), so a test can hold them: if a future edit
moves a cell, the icons would land on the wrong sprite and every prompt would show the wrong key.
"""
import re
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]

# Engage 2.0.0's Button sprite atlas rects (name, x, y, w, h; Unity bottom-left origin), read from
# icon/button/button.bundle. Geometry only.
GAME_OUTLINE = {
    'A': (44.06, 0.06, 39.89, 39.89), 'B': (0.06, 44.06, 39.89, 39.89),
    'X': (88.06, 0.06, 39.89, 39.89), 'Y': (44.06, 44.06, 39.89, 39.89),
    'L': (44.08, 132.08, 39.85, 35.90), 'R': (0.08, 132.08, 39.90, 35.90),
    'ZL': (132.08, 88.08, 39.85, 39.85), 'ZR': (0.03, 0.08, 39.95, 39.90),
    'Plus': (88.06, 44.06, 39.89, 39.89), 'Minus': (176.06, 0.08, 39.89, 39.87),
    'StickL': (176.08, 88.08, 37.85, 37.85), 'StickR': (218.08, 88.08, 37.85, 37.85),
    'StickRPush': (88.08, 132.03, 33.85, 40.90),
    'Up': (44.06, 88.06, 39.89, 39.89), 'Down': (88.06, 88.06, 39.89, 39.89),
    'Left': (0.06, 88.06, 39.89, 39.89), 'Right': (132.06, 0.06, 39.89, 39.89),
    'Home': (132.06, 44.08, 39.89, 39.87), 'Capture': (176.08, 44.08, 39.85, 39.85),
}


def load_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location('make_prompt_icons', ROOT / 'tools' / 'make_prompt_icons.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class PromptIconTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mpi = load_module()

    def test_rects_match_the_games_sprite_layout(self):
        mine = {r[0]: tuple(round(v, 2) for v in r[1:]) for r in self.mpi.OUTLINE_RECTS}
        self.assertEqual(set(mine), set(GAME_OUTLINE), 'every sprite of the atlas is drawn, and no other')
        for name, want in GAME_OUTLINE.items():
            got = mine[name]
            for a, b in zip(got, want):
                self.assertAlmostEqual(a, b, places=2, msg=f'{name}: rect {got} != {want}')

    def test_rects_stay_inside_the_atlas(self):
        for rects in (self.mpi.OUTLINE_RECTS, self.mpi.FILLED_RECTS):
            for name, x, y, w, h in rects:
                self.assertGreaterEqual(x, 0, name)
                self.assertGreaterEqual(y, 0, name)
                self.assertLessEqual(x + w, 256.001, name)
                self.assertLessEqual(y + h, 256.001, name)

    def test_generated_header_has_both_atlases(self):
        header = (ROOT / 'runtime' / 'prompt_icons.h').read_text(encoding='utf-8')
        for name, count in (('prompt_pc_outline', len(self.mpi.OUTLINE_RECTS)),
                            ('prompt_pc_filled', len(self.mpi.FILLED_RECTS))):
            self.assertIn(f'{name}_zstd[]', header)
            self.assertIn(f'{name}_count = {count}', header)
            self.assertIn(f'{name}_rects[]', header)
        # the blobs are zstd-compressed pictures, not text
        blob = re.search(r'prompt_pc_outline_zstd\[\] = \{(.*?)\};', header, re.S).group(1)
        self.assertGreater(len([b for b in blob.split(',') if b.strip()]), 2000)

    def test_every_cell_is_drawn(self):
        """Each sprite's cell has ink, and none of them is a plain solid block (a filled square would hide the legend).

        The outline atlas is line art (mostly empty, so a cell must not be a filled block). The solid atlas is the
        opposite by design: a filled cap with the legend knocked out, so its cell must be nearly full but not empty of a
        hole."""
        for picture, rects, solid in (('pc_outline', self.mpi.OUTLINE_RECTS, False),
                                      ('pc_filled', self.mpi.FILLED_RECTS, True)):
            path = ROOT / 'build' / 'prompt-icons' / f'{picture}.png'
            if not path.is_file():
                self.skipTest(f'{path.name} not generated yet (run tools/make_prompt_icons.py)')
            a = np.asarray(Image.open(path).convert('RGBA'))[:, :, 3]
            for name, x, y, w, h in rects:
                x0, y0, x1, y1 = [int(round(v)) for v in self.mpi.box((name, x, y, w, h))]
                cell = a[y0:y1, x0:x1]
                self.assertGreater(cell.max(), 40, f'{picture}/{name}: the cell is empty')
                coverage = (cell > 40).mean()
                if solid:
                    # a filled cap: ink nearly everywhere, with the legend cut out of it. A wide legend (Space, PrtSc,
                    # a two-letter key) leaves less ink, so the floor is a fifth of the cell.
                    self.assertGreater(coverage, 0.2, f'{picture}/{name}: the filled cap has no ink')
                    self.assertLess(coverage, 0.995, f'{picture}/{name}: the legend is not cut out')
                else:
                    self.assertLess(coverage, 0.92, f'{picture}/{name}: the cell is a solid block')


if __name__ == '__main__':
    unittest.main()
