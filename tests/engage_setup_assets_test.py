"""Packaging regression: the F1 menu needs its licensed host font, not just C++ source."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import make_engage_release


class SetupAssetsTest(unittest.TestCase):
    def test_menu_font_and_license_survive_source_copy(self):
        font = Path('runtime/ui/fonts/Roboto-Medium.ttf')
        license = Path('runtime/ui/fonts/LICENSE-Roboto.txt')
        frame_patch = Path('recomp/patches-engage-v200.txt')
        art = (Path('engage_setup/art/cathedral.jpg'), Path('engage_setup/art/title.webp'),
               Path('engage_setup/art/README.md'))
        data = (ROOT / font).read_bytes()
        self.assertGreater(len(data), 100)
        self.assertEqual(data[:4], b'\x00\x01\x00\x00')
        with tempfile.TemporaryDirectory() as temp:
            source, output = Path(temp) / 'source', Path(temp) / 'output'
            output.mkdir()
            for name in (font, license, frame_patch, *art, Path('VERSION'), Path('LICENSE'), Path('THIRD_PARTY_NOTICES.md')):
                target = source / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / name).read_bytes())
            paths = ('\0'.join(p.as_posix() for p in (font, license, frame_patch, *art)) + '\0').encode()
            with patch.object(make_engage_release, 'ROOT', source), patch.object(
                    make_engage_release.subprocess, 'check_output', return_value=paths):
                make_engage_release.copy_sources(output)
            self.assertEqual((output / font).read_bytes(), data)
            self.assertEqual((output / license).read_bytes(), (ROOT / license).read_bytes())
            self.assertEqual((output / frame_patch).read_bytes(), (ROOT / frame_patch).read_bytes())
            for name in art:
                self.assertEqual((output / name).read_bytes(), (ROOT / name).read_bytes())


if __name__ == '__main__':
    unittest.main()
