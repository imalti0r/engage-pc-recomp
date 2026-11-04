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
    def test_successful_setup_switches_to_installed_launcher_before_closing_parent(self):
        self.app.setup()
        wizard = self.app.wizard_app
        wizard.model.dest = str(self.dest)
        events = []
        wizard.on_installed = lambda: events.append('closed')
        with patch('engage_setup.installed_launcher.open_installed', side_effect=lambda dest: events.append('opened')):
            wizard.open_installed_launcher()
        self.assertEqual(events, ['opened', 'closed'])

    def test_failed_handoff_keeps_original_launcher_open(self):
        self.app.setup()
        wizard = self.app.wizard_app
        wizard.model.dest = str(self.dest)
        with patch('engage_setup.installed_launcher.open_installed', side_effect=OSError('synthetic start failure')), \
             patch('engage_setup.gui.messagebox.showerror') as error, patch.object(self.root, 'destroy') as close:
            wizard.open_installed_launcher()
        close.assert_not_called()
        error.assert_called_once()

    def setUp(self):
        import tkinter as tk
        from engage_setup.launcher_gui import Launcher
        from engage_setup.model import layout
        self.temp = tempfile.TemporaryDirectory()
        self.dest = Path(self.temp.name).resolve()
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
            self.app.mod_selected()
            self.app.toggle_button.invoke()
            self.assertEqual(read_settings(self.dest)['mods_disabled'], 'Test'.encode().hex())
            self.assertEqual(self.app.home.mod_count.get(), '0 enabled')

    def test_mod_search_filters_and_running_lock(self):
        from engage_setup.launcher import set_mod_enabled
        optional = self.dest / 'mods/Optional/romfs/file'
        optional.parent.mkdir(parents=True)
        optional.write_bytes(b'optional')
        unsupported = self.dest / 'mods/Unsupported'
        unsupported.mkdir()
        (unsupported / 'exefs').mkdir()
        set_mod_enabled(self.dest, 'Optional', False)
        self.app.refresh()
        self.assertIn('3 installed', self.app.mod_summary.get())
        self.app.mod_filter.set('Enabled')
        self.assertEqual([self.app.mods.item(k, 'text') for k in self.app.mods.get_children()], ['Test'])
        self.app.mod_filter.set('Disabled')
        self.assertEqual([self.app.mods.item(k, 'text') for k in self.app.mods.get_children()], ['Optional'])
        self.app.mod_filter.set('Needs attention')
        key, = self.app.mods.get_children()
        self.app.mods.selection_set(key)
        self.app.mod_selected()
        self.assertEqual(str(self.app.toggle_button['state']), 'disabled')
        self.assertIn('Code-only mod', self.app.mod_note.get())
        self.app.mod_filter.set('All mods')
        self.app.mod_search.set('TEST')
        key, = self.app.mods.get_children()
        self.app.mods.selection_set(key)
        self.app.mod_selected()
        self.assertEqual(self.app.toggle_button['text'], 'Disable mod')
        with patch.object(self.app, 'game_alive', return_value=True):
            self.app.mod_selected()
            self.assertEqual(str(self.app.toggle_button['state']), 'disabled')
        self.app.mod_search.set('nothing matches')
        self.assertEqual(self.app.mod_title.get(), 'No matching mods')

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

    def test_extracted_icon_stays_local_and_is_used_by_launcher(self):
        import ctypes
        from ctypes import wintypes
        from PIL import Image
        from engage_setup.game_icon import prepare_icon
        self.root.attributes('-alpha', 0)
        self.root.deiconify()
        self.root.update()
        user = ctypes.windll.user32
        user.GetParent.argtypes, user.GetParent.restype = [wintypes.HWND], wintypes.HWND
        user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user.SendMessageW.restype = ctypes.c_void_p
        window = user.GetParent(self.root.winfo_id())
        before_icon = user.SendMessageW(window, 0x007f, 1, 0)  # WM_GETICON, ICON_BIG
        source = self.dest / 'icon.jpg'
        Image.new('RGB', (256, 256), '#3060a0').save(source)
        icon = self.dest / 'engage.ico'
        self.assertTrue(prepare_icon(source, icon))
        self.assertEqual(icon.read_bytes()[:4], b'\x00\x00\x01\x00')
        self.app.refresh_icon()
        self.assertEqual(self.app.icon_stamp[0], str(icon))
        self.assertNotEqual(user.SendMessageW(window, 0x007f, 1, 0), before_icon)
        before = icon.read_bytes()
        source.write_bytes(b'not an image')
        self.assertFalse(prepare_icon(source, icon))
        self.assertEqual(icon.read_bytes(), before)

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

    def test_play_requests_foreground_for_the_child_without_changing_parent_environment(self):
        from types import SimpleNamespace
        previous = os.environ.get('TOTK_LAUNCH_FOREGROUND')
        child = SimpleNamespace(pid=12345, poll=lambda: None)
        with patch.object(self.app, 'require_idle'), \
             patch('engage_setup.launcher_gui.subprocess.Popen', return_value=child) as start, \
             patch('ctypes.windll.user32.AllowSetForegroundWindow', return_value=True) as allow:
            self.app.play()
        self.assertEqual(start.call_args.kwargs['env']['TOTK_LAUNCH_FOREGROUND'], '1')
        self.assertEqual(os.environ.get('TOTK_LAUNCH_FOREGROUND'), previous)
        allow.assert_called_once_with(child.pid)

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
