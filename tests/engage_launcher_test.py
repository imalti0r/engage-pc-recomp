"""Launcher persistence, mod import and save preservation on synthetic files."""
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engage_setup import launcher as ops


class LauncherTest(unittest.TestCase):
    def test_version_pill_distinguishes_development_and_release(self):
        self.assertEqual(ops.version_label('0.1.0-alpha.5', 'dev'), 'DEV · 0.1.0-alpha.5')
        self.assertEqual(ops.version_label('0.1.0-alpha.5', 'release'), 'v0.1.0-alpha.5')

    def test_settings_preserve_other_keys_and_comments_and_last_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'engage.ini'
            path.write_text('# keep\n[display]\nFULLSCREEN = 1\nfullscreen = 0\ncustom = keep-me\n')
            ops.write_settings(root, {'fullscreen': '1', 'fps_limit': '30'})
            text = path.read_text()
            self.assertIn('# keep', text)
            self.assertIn('custom = keep-me', text)
            self.assertEqual(ops.read_settings(root)['fullscreen'], '1')
            self.assertEqual(ops.read_settings(root)['fps_limit'], '30')
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                ops.write_settings(root, {'volume': '101'})
            self.assertEqual(path.read_bytes(), before)

    def test_zip_import_conflicts_and_toggle_preserve_missing_mod_setting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dest = root / 'install'
            dest.mkdir()
            archive = root / 'test.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('A/romfs/Data/file', b'original mod bytes')
            imported = ops.import_mod(dest, archive)
            self.assertEqual((imported / 'romfs/Data/file').read_bytes(), b'original mod bytes')
            with self.assertRaisesRegex(ValueError, 'already exists'):
                ops.import_mod(dest, archive)
            second = dest / 'mods/B/romfs/Data/file'
            second.parent.mkdir(parents=True)
            second.write_bytes(b'other')
            self.assertEqual([m.conflicts for m in ops.list_mods(dest)], [0, 1])
            ops.write_settings(dest, {'mods_disabled': '616273656e74'})
            ops.set_mod_enabled(dest, 'A', False)
            self.assertEqual([m.conflicts for m in ops.list_mods(dest)], [0, 0])
            self.assertEqual(ops.read_settings(dest)['mods_disabled'], '616273656e74,41')
            ops.set_mod_enabled(dest, 'A', True)
            self.assertEqual(ops.read_settings(dest)['mods_disabled'], '616273656e74')

    def test_zip_traversal_and_symlinks_leave_install_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dest = root / 'install'
            dest.mkdir()
            archive = root / 'bad.zip'
            for name in ('../escape', '/escape', 'C:/escape', 'a\\..\\escape'):
                with self.subTest(name=name):
                    with zipfile.ZipFile(archive, 'w') as z:
                        z.writestr(name, b'bad')
                    with self.assertRaises(ValueError):
                        ops.import_mod(dest, archive)
                    self.assertFalse(any((dest / 'mods').iterdir()))
            with zipfile.ZipFile(archive, 'w') as z:
                info = zipfile.ZipInfo('A/romfs/link')
                info.external_attr = 0o120777 << 16
                z.writestr(info, '/elsewhere')
            with self.assertRaises(ValueError):
                ops.import_mod(dest, archive)
            self.assertFalse((root / 'escape').exists())

    def test_backup_includes_pending_transaction_without_changing_saves(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('save/user/slot', 'save-tx/ready-1/user/slot'):
                path = root / 'profile' / name
                path.parent.mkdir(parents=True)
                path.write_bytes(name.encode())
            archive = ops.backup_saves(root)
            with zipfile.ZipFile(archive) as z:
                self.assertEqual(z.read('save/user/slot'), b'save/user/slot')
                self.assertEqual(z.read('save-tx/ready-1/user/slot'), b'save-tx/ready-1/user/slot')
            self.assertEqual((root / 'profile/save/user/slot').read_bytes(), b'save/user/slot')
            self.assertNotEqual(ops.backup_saves(root), archive)

    def test_code_only_mod_is_visible_but_cannot_be_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'mods/code/exefs').mkdir(parents=True)
            self.assertIn('Code-only', ops.list_mods(root)[0].problem)
            with self.assertRaises(ValueError):
                ops.set_mod_enabled(root, 'code', True)


if __name__ == '__main__':
    unittest.main()
