import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engage_setup import dpi, launcher


class DpiTest(unittest.TestCase):
    def test_scaling_follows_the_primary_monitor(self):
        class Root:
            tk = type('Tk', (), {'call': lambda self, *a: None})()

        for reported, expected in ((96, 1.0), (120, 1.25), (144, 1.5), (192, 2.0)):
            root = Root()   # a fresh root: scaled() caches the factor on it
            with self.subTest(dpi=reported), patch.object(dpi, 'dpi', return_value=reported), \
                    patch.object(dpi.os, 'name', 'posix'):
                self.assertAlmostEqual(dpi.apply(root), expected, places=3)
                self.assertEqual(dpi.scaled(root, (1120, 710)), (round(1120 * expected), round(710 * expected)))

    def test_enable_is_harmless_off_windows(self):
        with patch.object(dpi.os, 'name', 'posix'):
            self.assertFalse(dpi.enable())


class LauncherResolutionTest(unittest.TestCase):
    def test_the_launcher_offers_the_4k_sizes(self):
        # Engage: the window size is the game resolution, so that row carries the 4K sizes
        values = launcher.SETTINGS['window_size'][3]
        self.assertIn('3200x1800', values)
        self.assertIn('3840x2160', values)

    def test_the_launcher_settings_match_the_in_game_screen_tab(self):
        from engage_setup import launcher as ops
        # the rows the in-game Screen tab has that the launcher had none of
        for key in ('upscaler', 'dlss_mode', 'sharpness', 'aspect', 'render_scale', 'vk_present'):
            self.assertIn(key, ops.SETTINGS)
        self.assertEqual(ops.SETTINGS['upscaler'][3]['dlss'], 'NVIDIA DLSS')
        self.assertEqual(list(ops.SETTINGS['dlss_mode'][3]), ['dlaa', 'quality', 'balanced', 'performance', 'ultra'])
        # Engage takes its game resolution from the window, so the stale separate row is gone
        self.assertNotIn('output_res', ops.SETTINGS)

    def test_dlss_rows_follow_the_upscaler(self):
        from engage_setup import launcher as ops
        self.assertEqual([ops.row_visible(k, {'upscaler': 'dlss'}) for k in ('dlss_mode', 'sharpness')], [True, False])
        self.assertEqual([ops.row_visible(k, {'upscaler': 'fsr'}) for k in ('dlss_mode', 'sharpness')], [False, True])
        self.assertEqual([ops.row_visible(k, {'upscaler': 'bilinear'}) for k in ('dlss_mode', 'sharpness')],
                         [False, True])
        self.assertTrue(ops.row_visible('window_size', {'upscaler': 'dlss'}))


if __name__ == '__main__':
    unittest.main()
