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
                    # a two-letter key) leaves less ink, and the mouse is a narrow shape by design, so the floor is a
                    # tenth of the cell.
                    self.assertGreater(coverage, 0.1, f'{picture}/{name}: the filled cap has no ink')
                    self.assertLess(coverage, 0.995, f'{picture}/{name}: the legend is not cut out')
                else:
                    self.assertLess(coverage, 0.92, f'{picture}/{name}: the cell is a solid block')


    def test_the_drawn_icon_covers_eighty_percent_of_its_cell(self):
        """The picture is scaled to 80 % of the sprite cell and centred, so the prompts sit smaller on screen.

        Measured on the drawn atlases: the ink of a wide cell spans about 0.80 of the cell's side, and the same margin
        is left on both sides."""
        for picture, rects in (('pc_outline', self.mpi.OUTLINE_RECTS), ('pc_filled', self.mpi.FILLED_RECTS)):
            path = ROOT / 'build' / 'prompt-icons' / f'{picture}.png'
            if not path.is_file():
                self.skipTest(f'{path.name} not generated yet (run tools/make_prompt_icons.py)')
            a = np.asarray(Image.open(path).convert('RGBA'))[:, :, 3]
            for name, x, y, w, h in rects:
                label = self.mpi.LABELS.get(name)
                if label in ('mouse_l', 'mouse_r', 'mouse_look', 'arrow'):
                    continue    # a mouse or a d-pad arrow: narrow by shape, not by the scale
                x0, y0, x1, y1 = [int(round(v)) for v in self.mpi.box((name, x, y, w, h))]
                cell = a[y0:y1, x0:x1] > 40
                cols = np.where(cell.any(axis=0))[0]
                self.assertGreater(len(cols), 0, f'{picture}/{name}: empty cell')
                span = (cols[-1] - cols[0] + 1) / cell.shape[1]
                self.assertAlmostEqual(span, self.mpi.ICON_SCALE, delta=0.06,
                                       msg=f'{picture}/{name}: the icon spans {span:.2f} of its cell')
                left, right = cols[0], cell.shape[1] - 1 - cols[-1]
                self.assertLessEqual(abs(int(left) - int(right)), 3,
                                     f'{picture}/{name}: the icon is not centred ({left} px left, {right} px right)')


if __name__ == '__main__':
    unittest.main()
