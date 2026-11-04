"""Native launcher interactions against synthetic installs, never the player's files."""
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@unittest.skipUnless(os.name == 'nt', 'Windows desktop launcher')
class LauncherGuiTest(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from engage_setup.launcher_gui import Launcher
        from engage_setup.model import layout
        self.temp = tempfile.TemporaryDirectory()
        self.dest = Path(self.temp.name)
        for name in ('engage.exe', 'romfs-index.bin'):
            (self.dest / name).write_bytes(b'synthetic fixture')
        mod = self.dest / 'mods/Test/romfs/file'
        mod.parent.mkdir(parents=True)
        mod.write_bytes(b'mod')
        save = self.dest / 'profile/save/user/slot'
        save.parent.mkdir(parents=True)
        save.write_bytes(b'original save')
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = Launcher(self.root, layout(), self.dest, remember=False)

    def tearDown(self):
        if self.app.wizard and self.app.wizard.winfo_exists():
            self.app.wizard.destroy()
        self.root.destroy()
        self.temp.cleanup()

    def test_settings_and_mod_controls_write_shared_runtime_configuration(self):
        from tkinter import font
        self.assertEqual(font.Font(family=self.app.ui_font, size=11).actual('family'), 'Roboto Medium')
        from engage_setup.launcher import read_settings
        with patch.object(self.app, 'require_idle'):
            self.app.setting_vars['volume'].set('50%')
            self.app.save_settings_button.invoke()
            self.assertEqual(read_settings(self.dest)['volume'], '50')
            self.app.mods.selection_set('0')
            self.app.toggle_button.invoke()
            self.assertEqual(read_settings(self.dest)['mods_disabled'], 'Test'.encode().hex())
            self.assertEqual(self.app.home.mod_count.get(), '0 enabled')

    def test_first_launch_offers_existing_install_or_setup(self):
        self.app.dest = None
        self.app.refresh()
        self.assertEqual(self.app.play_button['text'], 'Set up Engage')
        self.app.play_button.invoke()
        self.assertEqual(self.app.current_page, 'setup')
        self.assertFalse(self.app.wizard)
        with patch('engage_setup.launcher_gui.filedialog.askdirectory', return_value=str(self.dest)):
            self.app.setup_existing_button.invoke()
        self.assertEqual(self.app.current_page, 'play')
        self.assertEqual(self.app.play_button['text'], 'Play Engage')

    def test_running_game_blocks_changes_and_launcher_remains_open(self):
        from engage_setup.launcher import read_settings
        class Game:
            def poll(self):
                return None
        self.app.game = Game()
        self.app.update_states()
        self.assertEqual(str(self.app.play_button['state']), 'disabled')
        self.assertEqual(str(self.app.backup_button['state']), 'disabled')
        self.assertEqual(str(self.app.home.backup['state']), 'disabled')
        self.app.mods.selection_set('0')
        self.app.toggle_mod()
        self.assertNotIn('mods_disabled', read_settings(self.dest))
        self.assertTrue(self.root.winfo_exists())

    def test_backup_action_copies_saves_and_setup_opens_from_same_launcher(self):
        with patch.object(self.app, 'require_idle'):
            self.app.backup_button.invoke()
        deadline = time.monotonic() + 4
        while self.app.busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertFalse(self.app.busy)
        self.assertEqual(len(list((self.dest / 'save-backups').glob('*.zip'))), 1)
        self.assertEqual((self.dest / 'profile/save/user/slot').read_bytes(), b'original save')
        self.app.setup_button.invoke()
        self.assertTrue(self.app.wizard.winfo_exists())
        self.assertEqual(self.app.wizard_app.vars['dest'].get(), str(self.dest))
        self.app.update_states()
        self.assertEqual(str(self.app.play_button['state']), 'disabled')

    def test_update_requires_confirmation_and_runs_prepare_off_the_ui_thread(self):
        from engage_setup.updates import Update
        info = Update('0.1.0-alpha.6', 'https://gitlab.com/engage-pc-recomp/engage-pc-recomp/-/releases/engage-v0.1.0-alpha.6',
                      'Engage-Setup-0.1.0-alpha.6-windows.zip')
        self.app.update_info = info
        self.app.layout.dev = False
        with patch.object(self.app, 'require_closed_game'), patch('engage_setup.launcher_gui.messagebox.askyesno', return_value=False):
            self.app.download_update()
        self.assertFalse(self.app.busy)
        target = self.dest / 'new-package'
        completed = []
        def finish(path):
            completed.append(path)
            self.app.busy = False
        with patch.object(self.app, 'require_closed_game'), \
             patch('engage_setup.launcher_gui.messagebox.askyesno', return_value=True), \
             patch('engage_setup.updates.prepare_update', return_value=target) as prepare, \
             patch('engage_setup.launcher_gui.subprocess.run', return_value=SimpleNamespace(returncode=0)), \
             patch.object(self.app, 'finish_launcher_update', side_effect=finish):
            self.app.download_update()
            deadline = time.monotonic() + 4
            while not completed and time.monotonic() < deadline:
                self.root.update()
                time.sleep(.01)
            self.assertEqual(completed, [target])
            prepare.assert_called_once()

    def test_offline_update_check_does_not_block_play(self):
        with patch('engage_setup.updates.check_for_update', side_effect=TimeoutError('offline')):
            self.app.check_updates(True)
            deadline = time.monotonic() + 3
            while self.app.update_running and time.monotonic() < deadline:
                self.root.update()
                time.sleep(.01)
        self.assertFalse(self.app.update_running)
        self.assertEqual(str(self.app.play_button['state']), 'normal')
        self.assertIn('Could not check', self.app.status.get())


if __name__ == '__main__':
    unittest.main()
