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
        for key in ('window_size', 'output_res'):
            values = launcher.SETTINGS[key][3]
            with self.subTest(key=key):
                self.assertIn('3200x1800', values)
                self.assertIn('3840x2160', values)


if __name__ == '__main__':
    unittest.main()
