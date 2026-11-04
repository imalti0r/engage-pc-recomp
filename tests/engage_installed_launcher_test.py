"""Installed launcher deployment and handoff, using synthetic packages only."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engage_setup.installed_launcher import install_launcher, installed_game, open_installed
from engage_setup.model import TITLE, Form
from engage_setup.pipeline import Pipeline, validate_destination
from installer.events import Reporter
from installer.guilogic import STEP_ORDER


class InstalledLauncherTest(unittest.TestCase):
    def test_setup_retries_launcher_copy_before_reporting_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source = root / 'download'
            self.package(source)
            dest = self.game(root / 'game')
            state = {'format': 1, 'title_id': TITLE, 'release': 'test', 'inputs': 'same', 'done': [], 'game_library': 1}
            (dest / 'engage-install.json').write_text(json.dumps(state))
            output = io.StringIO()
            pipeline = Pipeline(Form(dest=str(dest)), SimpleNamespace(root=source, dev=False, release='test'), Reporter(out=output))
            pipeline.check = lambda: None
            pipeline.fingerprint = lambda: 'same'
            pipeline.validate_resume = lambda: None
            pipeline.reuse_exefs = lambda: None
            for step in STEP_ORDER[1:]:
                setattr(pipeline, step, lambda: None)
            with patch('engage_setup.installed_launcher.install_launcher', side_effect=OSError('synthetic copy failure')):
                with self.assertRaisesRegex(OSError, 'copy failure'):
                    pipeline.run()
            self.assertNotIn('"result": "ok"', output.getvalue())
            pipeline.run()
            self.assertIn('"result": "ok"', output.getvalue())
            self.assertTrue((dest / 'Engage-Launcher.exe').is_file())

    def package(self, root, version='first'):
        for name in ('Engage-Launcher.exe', 'python/python.exe', 'python/pythonw.exe',
                     'engage_setup/gui.py', 'VERSION', 'llvm/bin/clang.exe', 'bin/nx_extract/nx_extract.exe'):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((version + name).encode())
        inventory = [{'path': p.relative_to(root).as_posix(), 'size': p.stat().st_size,
                      'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                     for p in root.rglob('*') if p.is_file() and p.name != 'setup-inventory.json']
        (root / 'setup-inventory.json').write_text(json.dumps(inventory))

    def game(self, root):
        root.mkdir()
        (root / 'engage-install.json').write_text(json.dumps({'format': 1, 'title_id': TITLE}))
        return root

    def test_installed_tools_survive_download_removal_and_game_folder_move(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source = root / 'download'
            self.package(source)
            # An unlisted private file must never be copied into the installed tools.
            (source / 'config.local.toml').write_text('private local input paths')
            dest = self.game(root / 'game')
            (dest / 'engage.ini').write_text('volume = 37')
            package = install_launcher(source, dest)
            self.assertFalse((package / 'config.local.toml').exists())
            self.assertTrue((package / 'llvm/bin/clang.exe').is_file())
            self.assertEqual(install_launcher(source, dest), package)
            self.assertEqual(installed_game(package), dest)
            self.assertEqual(validate_destination(dest, [], package), dest)
            source.rename(root / 'removed-download')
            dest.rename(root / 'moved-game')
            dest = root / 'moved-game'
            package = dest / '.launcher' / (dest / 'launcher-current.txt').read_text()
            self.assertEqual(installed_game(package), dest)
            self.assertEqual((dest / 'engage.ini').read_text(), 'volume = 37')
            self.assertTrue((package / 'python/pythonw.exe').is_file())

    def test_update_keeps_running_package_and_rejects_corruption_before_switching(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source = root / 'download'
            self.package(source)
            dest = self.game(root / 'game')
            previous = install_launcher(source, dest)
            marker = (dest / 'launcher-current.txt').read_bytes()
            self.package(source, 'next')
            (source / 'VERSION').write_text('corrupted')
            with self.assertRaisesRegex(ValueError, 'verification failed'):
                install_launcher(source, dest)
            self.assertEqual((dest / 'launcher-current.txt').read_bytes(), marker)
            self.assertTrue(previous.is_dir())
            self.package(source, 'next')
            updated = install_launcher(source, dest)
            self.assertNotEqual(updated, previous)
            self.assertTrue(previous.is_dir())
            self.assertEqual((dest / 'launcher-current.txt').read_text(), updated.name)

    def test_inventory_cannot_escape_package(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source = root / 'download'
            self.package(source)
            for name in ('../private', '/outside', 'C:/outside', '..\\outside'):
                (source / 'setup-inventory.json').write_text(json.dumps([{'path': name}]))
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'inventory path'):
                    install_launcher(source, root)

    def test_handoff_opens_the_installed_entry_and_completion_message(self):
        with tempfile.TemporaryDirectory() as temp, patch('engage_setup.installed_launcher.subprocess.Popen') as start:
            dest = Path(temp).resolve()
            open_installed(dest)
            start.assert_called_once_with([str(dest / 'Engage-Launcher.exe'), '--dest', str(dest), '--setup-complete'], cwd=dest)


if __name__ == '__main__':
    unittest.main()
