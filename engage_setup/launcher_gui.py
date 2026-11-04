"""Persistent desktop launcher using the setup app's bundled Python and Tk."""
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import zipfile
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import launcher as ops

BG, PANEL, INK, MUTED, GOLD = '#091426', '#101f35', '#eee9dd', '#a4afc0', '#ecc254'


class Launcher:
    def __init__(self, root, layout, dest=None, remember=True, apply_update=False):
        self.root, self.layout, self.remember = root, layout, remember
        self.after_ids = set()
        root.bind('<Destroy>', self.on_destroy, add='+')
        self.game, self.wizard, self.wizard_app, self.busy = None, None, None, False
        self.events = queue.Queue()
        self.update_events = queue.Queue()
        self.update_running, self.update_info = False, None
        self.update_install_events = queue.Queue()
        self.update_cancel = None
        self.state_path = Path(os.environ.get('APPDATA', Path.home())) / 'Engage PC Recomp/launcher.json'
        if not dest:
            try:
                saved = json.loads(self.state_path.read_text())
                dest = saved.get('install') if isinstance(saved, dict) else None
                if not isinstance(dest, str):
                    dest = None
            except (OSError, ValueError):
                pass
        if not dest and (layout.root / 'engage.exe').is_file():
            dest = layout.root
        self.dest = Path(dest).resolve() if dest else None
        self.status = tk.StringVar(value='All changes apply on next launch' if dest else 'Choose your game folder, or open Setup / Update to install.')
        self.location = tk.StringVar()
        self.setting_vars, self.settings_loaded, self.mod_rows = {}, {}, {}
        root.title('Engage PC Recomp')
        root.geometry('1120x710')
        root.minsize(980, 650)
        root.configure(bg=BG)
        icon = layout.runtime / 'engage-setup.ico'
        if os.name == 'nt' and icon.is_file():
            root.iconbitmap(default=str(icon))
        style = ttk.Style(root)
        style.theme_use('clam')
        from .launcher_typography import load_ui_font
        self.ui_font = load_ui_font(layout.runtime)
        style.configure('.', font=(self.ui_font, 11), background=BG, foreground=INK)
        style.configure('TFrame', background=BG)
        style.configure('TLabel', background=BG, foreground=INK)
        style.configure('Muted.TLabel', foreground=MUTED)
        style.configure('LauncherHeading.TLabel', font=(self.ui_font, 17, 'bold'))
        style.configure('SummaryHeading.TLabel', font=(self.ui_font, 15, 'bold'))
        style.configure('Footer.TLabel', font=(self.ui_font, 11, 'italic'), foreground=MUTED)
        style.configure('TEntry', fieldbackground=PANEL, foreground=INK, insertcolor=INK)
        style.configure('TButton', background=PANEL, foreground=INK, padding=(14, 9), borderwidth=1,
                        bordercolor='#31415a', lightcolor=PANEL, darkcolor=PANEL)
        style.configure('Nav.TButton', background=BG, foreground=MUTED, borderwidth=0,
                        font=(self.ui_font, 14), padding=(18, 8), lightcolor=BG, darkcolor=BG)
        style.configure('NavSelected.TButton', background=BG, foreground=INK, borderwidth=0,
                        font=(self.ui_font, 14, 'bold'), padding=(18, 8), lightcolor=BG, darkcolor=BG)
        style.configure('PlayNav.TButton', background=BG, foreground=MUTED, borderwidth=0,
                        font=('Georgia', 16), padding=(18, 8), lightcolor=BG, darkcolor=BG)
        style.configure('PlayNavSelected.TButton', background=BG, foreground=INK, borderwidth=0,
                        font=('Georgia', 16, 'bold'), padding=(18, 8), lightcolor=BG, darkcolor=BG)
        style.map('Nav.TButton', background=[('active', PANEL)])
        style.map('NavSelected.TButton', background=[('active', PANEL)])
        style.configure('Link.TButton', foreground=GOLD, background=BG, borderwidth=0,
                        font=(self.ui_font, 11), padding=0, lightcolor=BG, darkcolor=BG)
        style.map('Link.TButton', background=[('active', BG)], foreground=[('active', '#ffe09a')])
        style.map('TButton', background=[('active', '#293d58')], foreground=[('disabled', '#657184')])
        style.configure('TCombobox', fieldbackground=PANEL, background=PANEL, foreground=INK, padding=5,
                        font=(self.ui_font, 11), bordercolor='#31415a', lightcolor=PANEL, darkcolor=PANEL)
        style.map('TCombobox', fieldbackground=[('readonly', PANEL)], foreground=[('readonly', INK), ('disabled', MUTED)])
        style.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=INK, rowheight=34,
                        borderwidth=0, bordercolor='#29384a', lightcolor=BG, darkcolor=BG)
        style.configure('Treeview.Heading', background=BG, foreground=MUTED, padding=8,
                        font=(self.ui_font, 11), bordercolor='#29384a', lightcolor=BG, darkcolor=BG)
        style.map('Treeview', background=[('selected', '#314a6c')])
        outer = ttk.Frame(root)
        outer.pack(fill='both', expand=True)
        header = ttk.Frame(outer, padding=(26, 4), height=57)
        header.pack(fill='x')
        header.grid_propagate(False)
        header.columnconfigure(0, weight=2)
        header.columnconfigure(2, weight=1)
        from .launcher_controls import Pill
        Pill(header, ops.version_label(layout.release, getattr(layout, 'channel', 'dev'))).grid(row=0, column=0, sticky='w')
        nav = ttk.Frame(header)
        nav.grid(row=0, column=1)
        from .launcher_controls import Button
        Button(header, text='Settings', icon='settings', width=125, height=34,
               command=lambda: self.show('settings')).grid(row=0, column=2, sticky='e', padx=(0, 60))
        controls = ttk.Frame(header)
        controls.grid(row=0, column=3, sticky='e')
        from .launcher_chrome import Chrome
        self.chrome = Chrome(root, header, controls, self.close)
        ttk.Separator(outer).pack(fill='x')
        footer = ttk.Frame(outer, padding=(28, 14), height=65)
        footer.pack(side='bottom', fill='x')
        footer.pack_propagate(False)
        ttk.Label(footer, textvariable=self.status, style='Footer.TLabel', wraplength=750).pack(side='left')
        self.setup_button = Button(footer, text='Setup / Update', icon='download', plain=True,
                                   command=self.setup, width=168, height=34)
        self.setup_button.pack(side='right')
        ttk.Separator(outer).pack(side='bottom', fill='x')
        content = ttk.Frame(outer)
        content.pack(fill='both', expand=True)
        self.content = content
        self.update_bar = ttk.Frame(outer, padding=(28, 10))
        self.update_message = tk.StringVar()
        ttk.Label(self.update_bar, textvariable=self.update_message).pack(side='left')
        self.update_later = ttk.Button(self.update_bar, text='Later', command=self.dismiss_update)
        self.update_later.pack(side='right')
        self.update_now = ttk.Button(self.update_bar, text='Update now', command=self.download_update)
        self.update_now.pack(side='right', padx=12)
        self.update_progress = ttk.Progressbar(self.update_bar, length=140, maximum=100)
        self.pages, self.nav = {}, {}
        self.nav_lines = {}
        for key, title in [('play', 'Play'), ('mods', 'Mods'), ('saves', 'Saves'), ('settings', 'Settings')]:
            self.pages[key] = ttk.Frame(content, padding=0 if key == 'play' else (32, 25))
            if key == 'settings':
                continue
            item = ttk.Frame(nav)
            item.pack(side='left', padx=8)
            button = ttk.Button(item, text=title, width=5, style='Nav.TButton', command=lambda k=key: self.show(k))
            button.pack()
            self.nav_lines[key] = tk.Frame(item, bg=BG, height=2)
            self.nav_lines[key].pack(fill='x', padx=18)
            self.nav[key] = button
        self.build_play()
        self.build_settings()
        self.build_mods()
        self.build_saves()
        self.pages['setup'] = ttk.Frame(content, padding=(38, 30))
        self.build_setup_choice()
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.show('play')
        self.refresh()
        self.later(150, self.poll)
        if remember:
            self.later(1500, self.check_updates)
        if apply_update:
            self.later(600, self.apply_game_update)

    def later(self, milliseconds, action):
        slot = []
        def run():
            self.after_ids.discard(slot[0])
            action()
        slot.append(self.root.after(milliseconds, run))
        self.after_ids.add(slot[0])

    def on_destroy(self, event):
        if event.widget != self.root:
            return
        for pending in self.after_ids:
            self.root.after_cancel(pending)
        self.after_ids.clear()
        chrome = getattr(self, 'chrome', None)
        if chrome and chrome.pending:
            self.root.after_cancel(chrome.pending)
            chrome.pending = None

    def heading(self, page, title, description):
        ttk.Label(page, text=title, style='LauncherHeading.TLabel').pack(anchor='w')
        ttk.Label(page, text=description, style='Muted.TLabel', wraplength=650).pack(anchor='w', pady=(8, 20))

    def build_play(self):
        page = self.pages['play']
        from .launcher_home import Home
        self.home = Home(page, self)
        self.home.pack(fill='both', expand=True)
        self.play_button = self.home.play_button

    def build_settings(self):
        page = self.pages['settings']
        self.heading(page, 'Settings', 'Changes apply on next launch. F1 offers more settings in-game.')
        fields = ttk.Frame(page)
        fields.pack(fill='x')
        fields.columnconfigure((0, 1), weight=1, uniform='settings')
        self.setting_widgets = []
        for row, (key, (_, label, _, choices)) in enumerate(ops.SETTINGS.items()):
            field = ttk.Frame(fields)
            field.grid(row=row // 2, column=row % 2, sticky='ew', padx=(0, 24) if row % 2 == 0 else 0, pady=(0, 10))
            ttk.Label(field, text=label).pack(anchor='w', pady=(0, 5))
            var = tk.StringVar()
            self.setting_vars[key] = var
            widget = ttk.Combobox(field, textvariable=var, values=list(choices.values()), state='readonly', width=28)
            widget.pack(fill='x')
            self.setting_widgets.append(widget)
        self.save_settings_button = ttk.Button(page, text='Save settings', command=self.save_settings)
        self.save_settings_button.pack(anchor='w', pady=(18, 0))
        install = ttk.Frame(page)
        install.pack(fill='x', pady=(24, 0))
        self.choose_button = ttk.Button(install, text='Choose game folder', command=self.choose)
        self.choose_button.pack(side='left')
        self.refresh_button = ttk.Button(install, text='Refresh', command=self.refresh)
        self.refresh_button.pack(side='left', padx=10)
        self.check_updates_button = ttk.Button(install, text='Check for updates', command=lambda: self.check_updates(True))
        self.check_updates_button.pack(side='left')
        ttk.Label(page, textvariable=self.location, style='Muted.TLabel', wraplength=880).pack(anchor='w', pady=(10, 0))

    def build_mods(self):
        page = self.pages['mods']
        self.heading(page, 'RomFS mods', 'First folder alphabetically wins when files overlap. Extracted emulator RomFS mods are supported; code patches and Cobalt plugins are not.')
        listing = ttk.Frame(page)
        listing.pack(fill='both', expand=True)
        self.mods = ttk.Treeview(listing, columns=('enabled', 'files', 'conflicts'), show='tree headings', height=6, selectmode='browse')
        self.mods.heading('#0', text='Mod folder')
        self.mods.column('#0', width=260, minwidth=130)
        for key, title, width in [('enabled', 'State', 80), ('files', 'Files', 60), ('conflicts', 'Overridden', 90)]:
            self.mods.heading(key, text=title)
            self.mods.column(key, width=width, minwidth=55, stretch=False)
        scroll = ttk.Scrollbar(listing, orient='vertical', command=self.mods.yview)
        self.mods.configure(yscrollcommand=scroll.set)
        self.mods.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.mods.bind('<<TreeviewSelect>>', self.mod_selected)
        self.mods.bind('<space>', lambda _: self.toggle_mod())
        self.mod_note = tk.StringVar(value='No mods yet. Import a ZIP or an extracted mod folder.')
        ttk.Label(page, textvariable=self.mod_note, wraplength=650, style='Muted.TLabel').pack(anchor='w', pady=12)
        actions = ttk.Frame(page)
        actions.pack(fill='x')
        self.toggle_button = ttk.Button(actions, text='Enable / Disable', command=self.toggle_mod)
        self.toggle_button.pack(side='left')
        self.zip_button = ttk.Button(actions, text='Import ZIP', command=lambda: self.import_mod(False))
        self.zip_button.pack(side='left', padx=8)
        self.folder_button = ttk.Button(actions, text='Import folder', command=lambda: self.import_mod(True))
        self.folder_button.pack(side='left')
        self.open_mods_button = ttk.Button(page, text='Open mods folder', command=lambda: self.open_folder('mods'))
        self.open_mods_button.pack(anchor='w', pady=(10, 0))

    def build_saves(self):
        page = self.pages['saves']
        self.heading(page, 'Your saves', 'Load a save from the title menu in-game. Create a backup here with the game closed; backups include committed saves and any pending save transaction.')
        self.saves_note = tk.StringVar()
        ttk.Label(page, textvariable=self.saves_note, wraplength=650).pack(anchor='w', pady=(12, 20))
        self.backup_button = ttk.Button(page, text='Back up saves', command=self.backup)
        self.backup_button.pack(anchor='w')
        self.open_saves_button = ttk.Button(page, text='Open save folder', command=lambda: self.open_folder('profile/save'))
        self.open_saves_button.pack(anchor='w', pady=10)
        self.open_backups_button = ttk.Button(page, text='Open backups', command=lambda: self.open_folder('save-backups'))
        self.open_backups_button.pack(anchor='w')

    def build_setup_choice(self):
        page = self.pages['setup']
        self.heading(page, 'Set up Engage', 'Use a game you have already installed, or create an installation from your own game files.')
        ttk.Label(page, text='Already have an installed build?', style='SummaryHeading.TLabel').pack(anchor='w', pady=(12, 6))
        ttk.Label(page, text='Select the folder containing engage.exe and romfs-index.bin.', style='Muted.TLabel').pack(anchor='w')
        self.setup_existing_button = ttk.Button(page, text='Use existing install', command=self.choose)
        self.setup_existing_button.pack(anchor='w', pady=(12, 28))
        ttk.Separator(page).pack(fill='x')
        ttk.Label(page, text='Starting with game files?', style='SummaryHeading.TLabel').pack(anchor='w', pady=(28, 6))
        ttk.Label(page, text='Choose your base game, update 2.0.0, keys and firmware. Setup builds the game on this PC.',
                  style='Muted.TLabel', wraplength=850).pack(anchor='w')
        self.setup_new_button = ttk.Button(page, text='Set up from my game files', command=self.setup)
        self.setup_new_button.pack(anchor='w', pady=(12, 0))

    def show(self, key):
        self.current_page = key
        for name, page in self.pages.items():
            page.pack_forget()
            if name in self.nav:
                prefix = 'PlayNav' if name == 'play' else 'Nav'
                self.nav[name].configure(style=prefix + ('Selected.TButton' if name == key else '.TButton'))
                self.nav_lines[name].configure(bg=GOLD if name == key else BG)
        self.pages[key].pack(fill='both', expand=True)

    def installed(self):
        return self.dest is not None and (self.dest / 'engage.exe').is_file() and (self.dest / 'romfs-index.bin').is_file()

    def game_alive(self):
        return self.game is not None and self.game.poll() is None

    def require_idle(self):
        if not self.installed():
            raise ValueError('Choose an installed Engage game folder first.')
        self.require_closed_game()
        if self.wizard and self.wizard.winfo_exists():
            raise ValueError('Close Setup / Update before changing this installation.')

    def require_closed_game(self):
        if self.game_alive():
            raise ValueError('Close the game before changing settings, mods or saves.')
        if os.name == 'nt':
            tasklist = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/tasklist.exe'
            result = subprocess.run([str(tasklist), '/FI', 'IMAGENAME eq engage.exe', '/FO', 'CSV', '/NH'],
                                    capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode or b'"engage.exe"' in result.stdout.lower():
                raise ValueError('Close any running engage.exe before changing this installation.')

    def guarded(self, action):
        try:
            if self.busy:
                return
            self.require_idle()
            action()
        except (OSError, ValueError, zipfile.BadZipFile) as error:
            self.status.set(str(error))

    def refresh(self):
        try:
            values = ops.read_settings(self.dest) if self.dest else {}
            for key, (_, _, default, choices) in ops.SETTINGS.items():
                value = values.get(key, default)
                self.settings_loaded[key] = value
                label = choices.get(value, value)
                self.setting_vars[key].set(label)
                self.setting_widgets[list(ops.SETTINGS).index(key)].configure(values=list(choices.values()) + ([] if value in choices else [value]))
            self.mods.delete(*self.mods.get_children())
            self.mod_rows = {}
            for i, mod in enumerate(ops.list_mods(self.dest) if self.dest else []):
                key = str(i)
                self.mod_rows[key] = mod
                self.mods.insert('', 'end', iid=key, text=mod.name,
                                 values=('Unsupported' if mod.problem else 'On' if mod.enabled else 'Off', mod.files, mod.conflicts))
            self.mod_note.set('Select a mod to view details or enable/disable it.' if self.mod_rows else 'No mods yet. Import a ZIP or an extracted mod folder.')
            self.saves_note.set('Saves found in profile/save.' if self.dest and (self.dest / 'profile/save').is_dir() else 'No saves found yet. Save once in-game to create them.')
        except (OSError, ValueError) as error:
            self.status.set(str(error))
        self.location.set(str(self.dest) if self.dest else 'No game folder selected')
        self.home.set_summary(self.settings_loaded, list(self.mod_rows.values()))
        self.update_states()

    def update_states(self):
        ready, running = self.installed(), self.game_alive()
        setup_open = bool(self.wizard and self.wizard.winfo_exists())
        idle = ready and not running and not self.busy and not setup_open
        self.home.set_state(ready, running, self.busy or setup_open)
        for widget in (self.play_button, self.save_settings_button, self.toggle_button, self.zip_button,
                       self.folder_button, self.backup_button):
            widget.configure(state='normal' if idle else 'disabled')
        if not ready and not self.busy and not setup_open:
            if self.play_button['text'] != 'Set up Engage':
                self.play_button.configure(text='Set up Engage', icon='folder', command=lambda: self.show('setup'))
            self.play_button.configure(state='normal')
        elif self.play_button['text'] != 'Play Engage':
            self.play_button.configure(text='Play Engage', icon='play', command=self.play)
        for widget in self.setting_widgets:
            widget.configure(state='readonly' if idle else 'disabled')
        for widget in (self.open_mods_button, self.open_saves_button, self.open_backups_button):
            widget.configure(state='normal' if ready and not self.busy else 'disabled')
        for widget in (self.choose_button, self.setup_button, self.refresh_button):
            widget.configure(state='disabled' if running or self.busy else 'normal')

    def choose(self):
        path = filedialog.askdirectory(parent=self.root, title='Choose the folder containing engage.exe')
        if path:
            candidate = Path(path).resolve()
            if not (candidate / 'engage.exe').is_file():
                self.status.set('That folder does not contain engage.exe.')
                return
            self.dest = candidate
            if self.remember:
                try:
                    self.state_path.parent.mkdir(parents=True, exist_ok=True)
                    self.state_path.write_text(json.dumps({'install': str(self.dest)}), encoding='utf-8')
                except OSError as error:
                    self.status.set('Folder selected; could not remember it: ' + str(error))
            self.refresh()
            self.show('play')
            self.status.set('Game folder selected.')

    def play(self):
        def start():
            self.game = subprocess.Popen([str(self.dest / 'engage.exe')], cwd=self.dest)
            self.status.set('Game started. Settings, mods and save backups unlock after it exits.')
            self.update_states()
        self.guarded(start)

    def check_updates(self, manual=False):
        if self.update_running or self.busy:
            return
        self.update_running = True
        self.check_updates_button.configure(state='disabled')
        if manual:
            self.status.set('Checking for launcher updates…')
        def check():
            try:
                from .updates import check_for_update
                self.update_events.put((check_for_update(self.layout.release), None, manual))
            except Exception as error:
                self.update_events.put((None, str(error), manual))
        threading.Thread(target=check, daemon=True).start()

    def download_update(self):
        if not self.update_info or self.busy:
            return
        if self.layout.dev:
            self.status.set('Use the packaged launcher to install updates. Source checkouts are updated through Git.')
            return
        if self.game_alive() or (self.wizard and self.wizard.winfo_exists()):
            self.status.set('Close the game and Setup / Update before installing a launcher update.')
            return
        try:
            self.require_closed_game()
        except (OSError, ValueError) as error:
            self.status.set(str(error))
            return
        if not messagebox.askyesno('Update Engage PC Recomp',
                f'Download and install v{self.update_info.version} now?\n\n'
                'The launcher will restart, then update your selected game installation. '
                'Saves, mods and settings are kept. A game-code rebuild may be needed.', parent=self.root):
            return
        self.busy = True
        self.update_cancel = threading.Event()
        self.update_now.configure(state='disabled')
        self.update_later.configure(text='Cancel')
        self.update_progress.pack(side='right', padx=10)
        self.status.set('Preparing launcher update…')
        self.update_states()
        def install():
            try:
                from .updates import prepare_update
                def progress(done, total, phase):
                    self.update_install_events.put(('progress', (done, total, phase)))
                target = prepare_update(self.update_info, self.layout.root, progress, self.update_cancel)
                if self.update_cancel.is_set():
                    raise ValueError('Update cancelled. Your current version is unchanged.')
                self.update_install_events.put(('progress', (0, 0, 'Checking the new launcher…')))
                # Check the new Python/UI before changing old shortcuts; keep the GUI responsive.
                preflight = subprocess.run([str(target / 'python/python.exe'), '-I', '-c',
                        'import tkinter; import engage_setup.gui; import engage_setup.launcher_home'],
                        cwd=target, capture_output=True, timeout=30,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                if preflight.returncode:
                    raise ValueError('The new launcher failed its startup check. Your current version was kept.')
                self.update_install_events.put(('ready', target))
            except Exception as error:
                self.update_install_events.put(('error', str(error)))
        threading.Thread(target=install, daemon=False).start()

    def dismiss_update(self):
        if self.update_cancel and self.busy:
            self.update_cancel.set()
            self.status.set('Cancelling update…')
            return
        self.update_bar.pack_forget()
        self.status.set('Update postponed. You can keep playing.')

    def apply_game_update(self):
        if not self.installed():
            self.status.set('Launcher updated. Choose an existing game folder or set up Engage.')
            return
        try:
            self.require_closed_game()
        except (OSError, ValueError):
            self.status.set('Launcher updated. Close the running game, then select Setup / Update.')
            return
        self.setup()
        if self.wizard_app.form().finished() and not self.wizard_app.form().problems():
            self.wizard_app.start()
        else:
            self.status.set('Launcher updated. Select the files Setup needs to finish updating your game.')

    def finish_launcher_update(self, target):
        from .updates import activate_update
        if self.update_cancel and self.update_cancel.is_set():
            raise ValueError('Update cancelled. Your current version is unchanged.')
        activate_update(self.layout.root, target)
        args = [str(target / 'Engage-Launcher.exe'), '--apply-update']
        if self.dest:
            args += ['--dest', str(self.dest)]
        try:
            subprocess.Popen(args, cwd=target)
        except OSError:
            # The old bundle stays runnable if handoff cannot start.
            (self.layout.root / 'launcher-update.json').unlink(missing_ok=True)
            raise
        self.busy = False
        self.root.destroy()

    def save_settings(self):
        def save():
            changes = {}
            for key, var in self.setting_vars.items():
                choices = ops.SETTINGS[key][3]
                value = next((v for v, label in choices.items() if label == var.get()), var.get())
                if value != self.settings_loaded[key]:
                    changes[key] = value
            ops.write_settings(self.dest, changes)
            self.status.set('Settings saved for the next launch.')
            self.refresh()
        self.guarded(save)

    def mod_selected(self, _=None):
        selection = self.mods.selection()
        if selection:
            m = self.mod_rows[selection[0]]
            self.mod_note.set(m.problem or (f'{m.files} files · {m.conflicts} overridden by earlier mods.' +
                              (' Contains executable patches: those patches will be ignored.' if m.code else '')))

    def toggle_mod(self):
        def toggle():
            selection = self.mods.selection()
            if selection:
                m = self.mod_rows[selection[0]]
                ops.set_mod_enabled(self.dest, m.name, not m.enabled)
                self.refresh()
                self.status.set(f'{m.name}: {"disabled" if m.enabled else "enabled"} for the next launch.')
        self.guarded(toggle)

    def background(self, action, message):
        self.busy = True
        self.status.set(message)
        self.update_states()
        def run():
            try:
                result = action()
                self.events.put((True, str(result)))
            except Exception as error:
                self.events.put((False, str(error)))
        threading.Thread(target=run, daemon=False).start()

    def import_mod(self, folder):
        def choose():
            source = (filedialog.askdirectory(parent=self.root, title='Choose the extracted mod folder') if folder else
                      filedialog.askopenfilename(parent=self.root, title='Choose a RomFS mod ZIP', filetypes=[('ZIP archive', '*.zip')]))
            if source:
                self.background(lambda: ops.import_mod(self.dest, source), 'Importing mod…')
        self.guarded(choose)

    def backup(self):
        self.guarded(lambda: self.background(lambda: ops.backup_saves(self.dest), 'Backing up saves…'))

    def open_folder(self, relative):
        try:
            if self.dest:
                path = self.dest / relative
                path.mkdir(parents=True, exist_ok=True)
                os.startfile(path)
        except OSError as error:
            self.status.set(str(error))

    def setup(self):
        if self.wizard and self.wizard.winfo_exists():
            self.wizard.lift()
            return
        from .gui import App
        self.wizard = tk.Toplevel(self.root)
        app = App(self.wizard, 'en', self.layout)
        if self.dest:
            app.vars['dest'].set(str(self.dest))
        self.wizard_app = app
        app.play_button.configure(command=self.play_after_setup)
        self.status.set('Setup / Update is open in its own window. Refresh here when it finishes.')

    def play_after_setup(self):
        if self.wizard_app and self.wizard_app.model.result == 'ok':
            self.dest = Path(self.wizard_app.model.dest).resolve()
            self.wizard.destroy()
            self.refresh()
            self.play()

    def poll(self):
        try:
            while True:
                kind, value = self.update_install_events.get_nowait()
                if kind == 'progress':
                    done, total, phase = value
                    self.update_message.set(phase)
                    self.update_progress['value'] = done * 100 / total if total else 0
                elif kind == 'ready':
                    self.update_message.set('Checking the new launcher…')
                    try:
                        self.finish_launcher_update(value)
                        return
                    except (OSError, ValueError, subprocess.SubprocessError) as error:
                        self.update_install_events.put(('error', str(error)))
                else:
                    self.busy = False
                    self.update_cancel = None
                    self.update_now.configure(state='normal')
                    self.update_later.configure(text='Later')
                    self.update_progress.pack_forget()
                    self.update_message.set('Update did not finish. Your current launcher is available.')
                    self.status.set(str(value))
                    self.update_states()
        except queue.Empty:
            pass
        try:
            while True:
                update, error, manual = self.update_events.get_nowait()
                self.update_running = False
                self.check_updates_button.configure(state='normal')
                if update:
                    self.update_info = update
                    self.update_message.set(f'Launcher update v{update.version} is available.')
                    self.update_bar.pack(side='bottom', fill='x', before=self.content)
                elif manual:
                    self.status.set('Could not check updates. Try again later.' if error else 'No newer published setup is available.')
        except queue.Empty:
            pass
        try:
            while True:
                ok, message = self.events.get_nowait()
                self.busy = False
                self.refresh()
                self.status.set(('Finished: ' if ok else 'Could not finish: ') + message)
        except queue.Empty:
            pass
        if self.wizard_app and not self.wizard.winfo_exists():
            if self.wizard_app.model.result == 'ok':
                self.dest = Path(self.wizard_app.model.dest).resolve()
                if self.remember:
                    try:
                        self.state_path.parent.mkdir(parents=True, exist_ok=True)
                        self.state_path.write_text(json.dumps({'install': str(self.dest)}), encoding='utf-8')
                    except OSError as error:
                        self.status.set('Could not remember game folder: ' + str(error))
                self.refresh()
            self.wizard_app = None
        if self.game and self.game.poll() is not None:
            code = self.game.returncode
            self.game = None
            self.status.set('Game closed.' if code == 0 else f'Game exited with code {code}. Check the game’s logs folder.')
            self.refresh()
        self.update_states()
        self.later(500, self.poll)

    def close(self):
        if self.busy:
            self.status.set('Wait for the current operation to finish, or cancel the update, before closing.')
            return
        if self.wizard and self.wizard.winfo_exists():
            self.wizard.lift()
            self.status.set('Close the Setup / Update window first.')
            return
        self.root.destroy()
