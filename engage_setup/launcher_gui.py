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
from .i18n import LANGUAGES, load_language, save_language, set_language, tr

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
            from .installed_launcher import installed_game
            dest = installed_game(layout.root)
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
        self.ui_language = load_language()
        set_language(self.ui_language)
        self.status = tk.StringVar(value=tr('All changes apply on next launch') if dest else tr('Choose your game folder, or open Setup / Update to install.'))
        self.location = tk.StringVar()
        self.setting_vars, self.settings_loaded, self.mod_rows = {}, {}, {}
        self.icon_stamp = None
        root.title(tr('Engage PC Recomp'))
        from .dpi import scaled
        root.geometry('%dx%d' % scaled(root, (1120, 710)))
        root.minsize(*scaled(root, (980, 650)))
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
        self.build_window()
        self.later(150, self.poll)
        if remember:
            self.later(1500, self.check_updates)
        if apply_update:
            self.later(600, self.apply_game_update)

    def build_window(self):
        """Build the whole window. Called again when the interface language changes."""
        root = self.root
        if getattr(self, 'outer', None) is not None:
            self.outer.destroy()
        outer = self.outer = ttk.Frame(root)
        outer.pack(fill='both', expand=True)
        header = ttk.Frame(outer, padding=(26, 4), height=57)
        header.pack(fill='x')
        header.grid_propagate(False)
        header.columnconfigure((0, 2), weight=1, uniform='header-sides')
        from .launcher_controls import Pill
        Pill(header, ops.version_label(self.layout.release, getattr(self.layout, 'channel', 'dev'))).grid(row=0, column=0, sticky='w')
        nav = ttk.Frame(header)
        nav.grid(row=0, column=1)
        from .launcher_controls import Button
        right = ttk.Frame(header)
        right.grid(row=0, column=2, sticky='e')
        # interface language: the launcher's own wording, separate from the game's language setting. A menu button
        # rather than a combobox, whose field is sized in characters and overlapped the Settings button here.
        self.language_button = ttk.Button(right, text=LANGUAGES[self.ui_language], width=10,
                                         command=self.pick_language)
        self.language_button.pack(side='left', padx=(0, 10))
        Button(right, text=tr('Settings'), icon='settings', width=125, height=34,
               command=lambda: self.show('settings')).pack(side='left')
        ttk.Separator(outer).pack(fill='x')
        footer = ttk.Frame(outer, padding=(28, 14), height=65)
        footer.pack(side='bottom', fill='x')
        footer.pack_propagate(False)
        ttk.Label(footer, textvariable=self.status, style='Footer.TLabel', wraplength=750).pack(side='left')
        self.setup_button = Button(footer, text=tr('Setup / Update'), icon='download', plain=True,
                                   command=self.setup, width=168, height=34)
        self.setup_button.pack(side='right')
        ttk.Separator(outer).pack(side='bottom', fill='x')
        content = ttk.Frame(outer)
        content.pack(fill='both', expand=True)
        self.content = content
        self.update_bar = ttk.Frame(outer, padding=(28, 10))
        self.update_message = tk.StringVar()
        ttk.Label(self.update_bar, textvariable=self.update_message).pack(side='left')
        self.update_later = ttk.Button(self.update_bar, text=tr('Later'), command=self.dismiss_update)
        self.update_later.pack(side='right')
        self.update_now = ttk.Button(self.update_bar, text=tr('Update now'), command=self.download_update)
        self.update_now.pack(side='right', padx=12)
        self.update_progress = ttk.Progressbar(self.update_bar, length=140, maximum=100)
        self.pages, self.nav = {}, {}
        self.nav_lines = {}
        for key, title in [('play', tr('Play')), ('mods', tr('Mods')), ('saves', tr('Saves')), ('settings', tr('Settings'))]:
            self.pages[key] = ttk.Frame(content, padding=0 if key == 'play' else (32, 25))
            if key == 'settings':
                continue
            item = ttk.Frame(nav)
            item.pack(side='left', padx=8)
            button = ttk.Button(item, text=title, width=6, style='Nav.TButton', command=lambda k=key: self.show(k))
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
        self.update_states()

    def pick_language(self):
        """A small menu under the language button: the launcher's own wording, not the game's language."""
        menu = tk.Menu(self.root, tearoff=False, bg=PANEL, fg=INK, activebackground='#314a6c',
                       activeforeground=INK, borderwidth=0)
        for code, label in LANGUAGES.items():
            menu.add_command(label=label, command=lambda c=code: self.change_language(c))
        x = self.language_button.winfo_rootx()
        y = self.language_button.winfo_rooty() + self.language_button.winfo_height()
        menu.tk_popup(x, y)

    def change_language(self, wanted):
        """Switch the launcher's own wording and rebuild the window in it."""
        if wanted == self.ui_language:
            return
        self.ui_language = set_language(wanted)
        save_language(wanted)
        self.root.title(tr('Engage PC Recomp'))
        self.status.set(tr('Language changed.'))
        self.build_window()

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

    def heading(self, page, title, description):
        ttk.Label(page, text=tr(title), style='LauncherHeading.TLabel').pack(anchor='w')
        ttk.Label(page, text=tr(description), style='Muted.TLabel', wraplength=650).pack(anchor='w', pady=(8, 20))

    def build_play(self):
        page = self.pages['play']
        from .launcher_home import Home
        self.home = Home(page, self)
        self.home.pack(fill='both', expand=True)
        self.play_button = self.home.play_button

    def build_settings(self):
        page = self.pages['settings']
        self.heading(page, 'Settings', 'Changes apply on next launch. F1 offers more settings in-game.')
        self.fields = ttk.Frame(page)
        self.fields.pack(fill='x')
        # three columns: eleven rows two-up would push the install controls off the window
        self.fields.columnconfigure((0, 1, 2), weight=1, uniform='settings')
        self.setting_widgets, self.setting_rows = [], {}
        self.setting_labels = {}      # key -> {value: the label shown in this interface language}
        for key, (_, label, _, choices) in ops.SETTINGS.items():
            field = ttk.Frame(self.fields)
            ttk.Label(field, text=tr(label)).pack(anchor='w', pady=(0, 5))
            var = tk.StringVar()
            self.setting_vars[key] = var
            if choices is None:
                # free text (the 3D render scale): "Game default" or a percentage the game accepts
                widget = ttk.Entry(field, textvariable=var, width=28)
                widget.pack(fill='x')
                hint = ttk.Label(field, text=tr('Game default, or ') + f'{ops.RENDER_SCALE_MIN}–{ops.RENDER_SCALE_MAX} %',
                                 style='Muted.TLabel')
                hint.pack(anchor='w', pady=(4, 0))
                if key == 'render_scale':
                    var.trace_add('write', lambda *_, v=var: self.render_scale_typed(v))
            else:
                labels = self.setting_labels[key] = {value: tr(text) for value, text in choices.items()}
                widget = ttk.Combobox(field, textvariable=var, values=list(labels.values()), state='readonly', width=28)
                widget.pack(fill='x')
            self.setting_rows[key] = field
            self.setting_widgets.append(widget)
        # a row appears and disappears with the upscaler, so the grid is laid out again whenever that changes
        self.setting_vars['upscaler'].trace_add('write', lambda *_: self.layout_settings(self.current_settings()))
        self.save_settings_button = ttk.Button(page, text=tr('Save settings'), command=self.save_settings)
        self.save_settings_button.pack(anchor='w', pady=(18, 0))
        install = ttk.Frame(page)
        install.pack(fill='x', pady=(24, 0))
        self.choose_button = ttk.Button(install, text=tr('Choose game folder'), command=self.choose)
        self.choose_button.pack(side='left')
        self.refresh_button = ttk.Button(install, text=tr('Refresh'), command=self.refresh)
        self.refresh_button.pack(side='left', padx=10)
        self.check_updates_button = ttk.Button(install, text=tr('Check for updates'), command=lambda: self.check_updates(True))
        self.check_updates_button.pack(side='left')
        ttk.Label(page, textvariable=self.location, style='Muted.TLabel', wraplength=880).pack(anchor='w', pady=(10, 0))

    def current_settings(self):
        """The page's values under their setting keys (the comboboxes show labels, the ini stores values)."""
        values = {}
        for key, var in self.setting_vars.items():
            choices = ops.SETTINGS[key][3]
            if choices is None:   # a free-text row: what the player typed, in ini form
                values[key] = ops.render_scale_value(var.get()) if key == 'render_scale' else var.get().strip()
                continue
            labels = self.setting_labels[key]
            values[key] = next((v for v, label in labels.items() if label == var.get()), var.get())
        return values

    def render_scale_typed(self, var):
        """Colour the 3D render scale field when what was typed is not a value the game accepts."""
        value = ops.render_scale_value(var.get())
        state = 'Invalid' if value is None else ''
        if getattr(self, 'render_scale_state', None) != state:
            self.render_scale_state = state
            self.status.set(tr('3D render scale must be Game default or ') + f'{ops.RENDER_SCALE_MIN}–{ops.RENDER_SCALE_MAX} %.'
                            if state == 'Invalid' else '')

    def layout_settings(self, values):
        """Place the rows that apply for these values, two per line (SETTINGS_NEEDS)."""
        shown = [key for key in ops.SETTINGS if ops.row_visible(key, values)]
        for key in ops.SETTINGS:
            self.setting_rows[key].grid_forget()
        for row, key in enumerate(shown):
            self.setting_rows[key].grid(row=row // 3, column=row % 3, sticky='ew',
                                        padx=(0, 24) if row % 3 < 2 else 0, pady=(0, 10))

    def build_mods(self):
        page = self.pages['mods']
        self.heading(page, 'Your mods', 'RomFS mods are supported. Cobalt plugins and code patches are not available yet.')
        toolbar = ttk.Frame(page)
        toolbar.pack(fill='x', pady=(8, 14))
        self.mod_search = tk.StringVar()
        ttk.Label(toolbar, text=tr('Search')).pack(side='left', padx=(0, 8))
        ttk.Entry(toolbar, textvariable=self.mod_search, width=28).pack(side='left', fill='x', expand=True)
        self.mod_filter = tk.StringVar(value=tr('All mods'))
        ttk.Combobox(toolbar, textvariable=self.mod_filter, state='readonly', width=17,
                     values=(tr('All mods'), tr('Enabled'), tr('Disabled'), tr('Needs attention'))).pack(side='left', padx=(12, 0))
        self.mod_summary = tk.StringVar()
        ttk.Label(page, textvariable=self.mod_summary, style='Muted.TLabel').pack(anchor='w', pady=(0, 10))
        listing = ttk.Frame(page)
        listing.pack(fill='both', expand=True)
        self.mods = ttk.Treeview(listing, columns=('enabled', 'files', 'conflicts'), show='tree headings', height=4, selectmode='browse')
        self.mods.heading('#0', text=tr('Mod'))
        self.mods.column('#0', width=260, minwidth=130)
        for key, title, width in [('enabled', 'Status', 130), ('files', 'Files', 65), ('conflicts', 'Overlaps', 85)]:
            self.mods.heading(key, text=tr(title))
            self.mods.column(key, width=width, minwidth=55, stretch=False)
        scroll = ttk.Scrollbar(listing, orient='vertical', command=self.mods.yview)
        self.mods.configure(yscrollcommand=scroll.set)
        self.mods.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.mods.bind('<<TreeviewSelect>>', self.mod_selected)
        self.mods.bind('<space>', lambda _: self.toggle_mod())
        self.mod_title = tk.StringVar(value=tr('Select a mod'))
        ttk.Separator(page).pack(fill='x', pady=(16, 12))
        ttk.Label(page, textvariable=self.mod_title, font=(self.ui_font, 14)).pack(anchor='w')
        self.mod_note = tk.StringVar(value=tr('Import a ZIP or an extracted mod folder to get started.'))
        ttk.Label(page, textvariable=self.mod_note, wraplength=650, style='Muted.TLabel').pack(anchor='w', pady=12)
        actions = ttk.Frame(page)
        actions.pack(fill='x')
        self.toggle_button = ttk.Button(actions, text=tr('Enable / Disable'), command=self.toggle_mod)
        self.toggle_button.pack(side='left')
        self.zip_button = ttk.Button(actions, text=tr('Import ZIP'), command=lambda: self.import_mod(False))
        self.zip_button.pack(side='left', padx=8)
        self.folder_button = ttk.Button(actions, text=tr('Import folder'), command=lambda: self.import_mod(True))
        self.folder_button.pack(side='left')
        self.open_mods_button = ttk.Button(actions, text=tr('Open mods folder'), command=lambda: self.open_folder('mods'))
        self.open_mods_button.pack(side='right')
        self.mod_search.trace_add('write', lambda *_: self.render_mods())
        self.mod_filter.trace_add('write', lambda *_: self.render_mods())

    def build_saves(self):
        page = self.pages['saves']
        self.heading(page, 'Your saves', 'Load a save from the title menu in-game. Create a backup here with the game closed; backups include committed saves and any pending save transaction.')
        self.saves_note = tk.StringVar()
        ttk.Label(page, textvariable=self.saves_note, wraplength=650).pack(anchor='w', pady=(12, 20))
        self.backup_button = ttk.Button(page, text=tr('Back up saves'), command=self.backup)
        self.backup_button.pack(anchor='w')
        self.open_saves_button = ttk.Button(page, text=tr('Open save folder'), command=lambda: self.open_folder('profile/save'))
        self.open_saves_button.pack(anchor='w', pady=10)
        self.open_backups_button = ttk.Button(page, text=tr('Open backups'), command=lambda: self.open_folder('save-backups'))
        self.open_backups_button.pack(anchor='w')

    def build_setup_choice(self):
        page = self.pages['setup']
        self.heading(page, 'Set up Engage', 'Use a game you have already installed, or create an installation from your own game files.')
        ttk.Label(page, text=tr('Already have an installed build?'), style='SummaryHeading.TLabel').pack(anchor='w', pady=(12, 6))
        ttk.Label(page, text=tr('Select the folder containing engage.exe and romfs-index.bin.'), style='Muted.TLabel').pack(anchor='w')
        self.setup_existing_button = ttk.Button(page, text=tr('Use existing install'), command=self.choose)
        self.setup_existing_button.pack(anchor='w', pady=(12, 28))
        ttk.Separator(page).pack(fill='x')
        ttk.Label(page, text=tr('Starting with game files?'), style='SummaryHeading.TLabel').pack(anchor='w', pady=(28, 6))
        ttk.Label(page, text=tr('Choose your base game, update 2.0.0, keys and firmware. Setup builds the game on this PC.'),
                  style='Muted.TLabel', wraplength=850).pack(anchor='w')
        self.setup_new_button = ttk.Button(page, text=tr('Set up from my game files'), command=self.setup)
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
            raise ValueError(tr('Choose an installed Engage game folder first.'))
        self.require_closed_game()
        if self.wizard and self.wizard.winfo_exists():
            raise ValueError(tr('Close Setup / Update before changing this installation.'))

    def require_closed_game(self):
        if self.game_alive():
            raise ValueError(tr('Close the game before changing settings, mods or saves.'))
        if os.name == 'nt':
            tasklist = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/tasklist.exe'
            result = subprocess.run([str(tasklist), '/FI', 'IMAGENAME eq engage.exe', '/FO', 'CSV', '/NH'],
                                    capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode or b'"engage.exe"' in result.stdout.lower():
                raise ValueError(tr('Close any running engage.exe before changing this installation.'))

    def guarded(self, action):
        try:
            if self.busy:
                return
            self.require_idle()
            action()
        except (OSError, ValueError, zipfile.BadZipFile) as error:
            self.status.set(str(error))

    def refresh(self):
        self.refresh_icon()
        try:
            values = ops.read_settings(self.dest) if self.dest else {}
            for key, (_, _, default, choices) in ops.SETTINGS.items():
                value = values.get(key, default)
                self.settings_loaded[key] = value
                if choices is None:   # a free-text row (the 3D render scale)
                    self.setting_vars[key].set(tr('Game default') if value == 'game' else ops.render_scale_text(value))
                    continue
                labels = self.setting_labels[key]
                self.setting_vars[key].set(labels.get(value, value))
                self.setting_widgets[list(ops.SETTINGS).index(key)].configure(values=list(labels.values()) + ([] if value in labels else [value]))
            self.layout_settings(self.settings_loaded)
            selection = self.mods.selection()
            selected_name = self.mod_rows[selection[0]].name if selection and selection[0] in self.mod_rows else None
            self.mod_rows = {}
            for i, mod in enumerate(ops.list_mods(self.dest) if self.dest else []):
                key = str(i)
                self.mod_rows[key] = mod
            self.render_mods(selected_name)
            self.saves_note.set(tr('Saves found in profile/save.') if self.dest and (self.dest / 'profile/save').is_dir() else tr('No saves found yet. Save once in-game to create them.'))
        except (OSError, ValueError) as error:
            self.status.set(str(error))
        self.location.set(str(self.dest) if self.dest else tr('No game folder selected'))
        self.home.set_summary(self.settings_loaded, list(self.mod_rows.values()))
        self.update_states()

    def refresh_icon(self):
        if os.name != 'nt':
            return
        icons = ([self.dest / 'engage.ico'] if self.dest else []) + [self.layout.runtime / 'engage-setup.ico']
        for icon in icons:
            try:
                stat = icon.stat()
                stamp = str(icon), stat.st_mtime_ns, stat.st_size
                if stamp != self.icon_stamp:
                    self.root.iconbitmap(str(icon))
                    self.icon_stamp = stamp
                return
            except (OSError, tk.TclError):
                continue

    def update_states(self):
        ready, running = self.installed(), self.game_alive()
        setup_open = bool(self.wizard and self.wizard.winfo_exists())
        idle = ready and not running and not self.busy and not setup_open
        self.home.set_state(ready, running, self.busy or setup_open)
        for widget in (self.play_button, self.save_settings_button, self.toggle_button, self.zip_button,
                       self.folder_button, self.backup_button):
            widget.configure(state='normal' if idle else 'disabled')
        if not ready and not self.busy and not setup_open:
            if self.play_button['text'] != tr('Set up Engage'):
                self.play_button.configure(text=tr('Set up Engage'), icon='folder', command=lambda: self.show('setup'))
            self.play_button.configure(state='normal')
        elif self.play_button['text'] != tr('Play Engage'):
            self.play_button.configure(text=tr('Play Engage'), icon='play', command=self.play)
        for widget in self.setting_widgets:
            widget.configure(state='readonly' if idle else 'disabled')
        for widget in (self.open_mods_button, self.open_saves_button, self.open_backups_button):
            widget.configure(state='normal' if ready and not self.busy else 'disabled')
        for widget in (self.choose_button, self.setup_button, self.refresh_button):
            widget.configure(state='disabled' if running or self.busy else 'normal')
        selection = self.mods.selection()
        if not selection or self.mod_rows[selection[0]].problem:
            self.toggle_button.configure(state='disabled')

    def choose(self):
        path = filedialog.askdirectory(parent=self.root, title=tr('Choose the folder containing engage.exe'))
        if path:
            candidate = Path(path).resolve()
            if not (candidate / 'engage.exe').is_file():
                self.status.set(tr('That folder does not contain engage.exe.'))
                return
            self.dest = candidate
            if self.remember:
                try:
                    self.state_path.parent.mkdir(parents=True, exist_ok=True)
                    self.state_path.write_text(json.dumps({'install': str(self.dest)}), encoding='utf-8')
                except OSError as error:
                    self.status.set(tr('Folder selected; could not remember it: ') + str(error))
            self.refresh()
            self.show('play')
            self.status.set(tr('Game folder selected.'))

    def play(self):
        def start():
            self.game = ops.launch_game(self.dest)
            self.status.set(tr('Game started. Settings, mods and save backups unlock after it exits.'))
            self.update_states()
        self.guarded(start)

    def check_updates(self, manual=False):
        if self.update_running or self.busy:
            return
        self.update_running = True
        self.check_updates_button.configure(state='disabled')
        if manual:
            self.status.set(tr('Checking for launcher updates…'))
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
            self.status.set(tr('Use the packaged launcher to install updates. Source checkouts are updated through Git.'))
            return
        if self.game_alive() or (self.wizard and self.wizard.winfo_exists()):
            self.status.set(tr('Close the game and Setup / Update before installing a launcher update.'))
            return
        try:
            self.require_closed_game()
        except (OSError, ValueError) as error:
            self.status.set(str(error))
            return
        if not messagebox.askyesno(tr('Update Engage PC Recomp'),
                tr('Download and install v') + f'{self.update_info.version}' +
                tr(' now?\n\nThe launcher will restart, then update your selected game installation. Saves, mods and settings are kept. A game-code rebuild may be needed.'), parent=self.root):
            return
        self.busy = True
        self.update_cancel = threading.Event()
        self.update_now.configure(state='disabled')
        self.update_later.configure(text=tr('Cancel'))
        self.update_progress.pack(side='right', padx=10)
        self.status.set(tr('Preparing launcher update…'))
        self.update_states()
        def install():
            try:
                from .updates import prepare_update
                def progress(done, total, phase):
                    self.update_install_events.put(('progress', (done, total, phase)))
                target = prepare_update(self.update_info, self.layout.root, progress, self.update_cancel)
                if self.update_cancel.is_set():
                    raise ValueError(tr('Update cancelled. Your current version is unchanged.'))
                self.update_install_events.put(('progress', (0, 0, tr('Checking the new launcher…'))))
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
            self.status.set(tr('Cancelling update…'))
            return
        self.update_bar.pack_forget()
        self.status.set(tr('Update postponed. You can keep playing.'))

    def apply_game_update(self):
        if not self.installed():
            self.status.set(tr('Launcher updated. Choose an existing game folder or set up Engage.'))
            return
        try:
            self.require_closed_game()
        except (OSError, ValueError):
            self.status.set(tr('Launcher updated. Close the running game, then select Setup / Update.'))
            return
        self.setup()
        if self.wizard_app.form().finished() and not self.wizard_app.form().problems():
            self.wizard_app.start()
        else:
            self.status.set(tr('Launcher updated. Select the files Setup needs to finish updating your game.'))

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
            values = self.current_settings()
            invalid = [tr(ops.SETTINGS[k][1]) for k, v in values.items() if v is None]
            if invalid:
                raise ValueError('，'.join(invalid) + tr(' must be Game default or ') + f'{ops.RENDER_SCALE_MIN}–'
                                                      f'{ops.RENDER_SCALE_MAX} %.')
            changes = {}
            for key, value in values.items():
                if value != self.settings_loaded[key]:
                    changes[key] = value
            ops.write_settings(self.dest, changes)
            notice = tr('Settings saved for the next launch.')
            if 'window_size' in changes:
                # Engage allocates its window textures once, at start: a new game resolution cannot take effect while
                # it runs (the runtime pushes the console-mode change, but Unity never re-enumerates the display).
                notice = tr('Window size saved — it applies when the game next starts.')
            self.status.set(notice)
            self.refresh()
        self.guarded(save)

    def mod_selected(self, _=None):
        selection = self.mods.selection()
        if selection:
            m = self.mod_rows[selection[0]]
            self.mod_title.set(m.name)
            self.toggle_button.configure(text=tr('Disable mod') if m.enabled else tr('Enable mod'))
            self.toggle_button.configure(state='normal' if self.installed() and not self.game_alive() and not self.busy and not m.problem else 'disabled')
            self.mod_note.set(m.problem or (f'{m.files}' + tr(' files · ') + f'{m.conflicts}' + tr(' overridden by earlier mods.') +
                              (tr(' Contains executable patches: those patches will be ignored.') if m.code else '') +
                              tr('\nChanges apply on the next launch.')))
            if m.problem:
                self.toggle_button.configure(state='disabled')
        else:
            self.mod_title.set(tr('Select a mod') if self.mod_rows else tr('Build your collection'))
            self.mod_note.set(tr('Select a mod to see its files, conflicts and compatibility.') if self.mod_rows else
                              tr('Import a ZIP or an extracted mod folder to get started.'))
            self.toggle_button.configure(state='disabled')

    def render_mods(self, preferred=None):
        selected = self.mods.selection()
        name = preferred or (self.mod_rows[selected[0]].name if selected and selected[0] in self.mod_rows else None)
        self.mods.delete(*self.mods.get_children())
        query, mode = self.mod_search.get().casefold(), self.mod_filter.get()
        enabled = sum(m.enabled and not m.problem for m in self.mod_rows.values())
        attention = sum(bool(m.problem or m.conflicts) for m in self.mod_rows.values())
        self.mod_summary.set(f'{len(self.mod_rows)}' + tr(' installed    ·    ') + f'{enabled}' + tr(' enabled    ·    ') + f'{attention}' + tr(' need attention'))
        for key, m in self.mod_rows.items():
            if query not in m.name.casefold() or (mode == 'Enabled' and (not m.enabled or m.problem)) or \
               (mode == 'Disabled' and (m.enabled or m.problem)) or \
               (mode == 'Needs attention' and not (m.problem or m.conflicts)):
                continue
            self.mods.insert('', 'end', iid=key, text=m.name,
                             values=(tr('Unavailable') if m.problem else tr('Enabled') if m.enabled else tr('Disabled'), m.files, m.conflicts or '—'))
            if m.name == name:
                self.mods.selection_set(key)
        self.mod_selected()
        if self.mod_rows and not self.mods.get_children():
            self.mod_title.set(tr('No matching mods'))
            self.mod_note.set(tr('Try another search or choose All mods.'))

    def toggle_mod(self):
        def toggle():
            selection = self.mods.selection()
            if selection:
                m = self.mod_rows[selection[0]]
                ops.set_mod_enabled(self.dest, m.name, not m.enabled)
                self.refresh()
                self.status.set(f'{m.name}: ' + tr('disabled') + ' / ' + tr('enabled'))
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
            source = (filedialog.askdirectory(parent=self.root, title=tr('Choose the extracted mod folder')) if folder else
                      filedialog.askopenfilename(parent=self.root, title=tr('Choose a RomFS mod ZIP'), filetypes=[(tr('ZIP archive'), '*.zip')]))
            if source:
                self.background(lambda: ops.import_mod(self.dest, source), tr('Importing mod…'))
        self.guarded(choose)

    def backup(self):
        self.guarded(lambda: self.background(lambda: ops.backup_saves(self.dest), tr('Backing up saves…')))

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
        app = App(self.wizard, self.ui_language, self.layout)
        if self.dest:
            app.vars['dest'].set(str(self.dest))
        self.wizard_app = app
        app.on_installed = self.root.destroy
        app.play_button.configure(command=self.play_after_setup)
        self.status.set(tr('Setup / Update is open in its own window. Refresh here when it finishes.'))

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
                    self.update_later.configure(text=tr('Later'))
                    self.update_progress.pack_forget()
                    self.update_message.set(tr('Update did not finish. Your current launcher is available.'))
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
                    self.update_message.set(tr('Launcher update v') + f'{update.version}' + tr(' is available.'))
                    self.update_bar.pack(side='bottom', fill='x', before=self.content)
                elif manual:
                    self.status.set(tr('Could not check updates. Try again later.') if error else tr('No newer published setup is available.'))
        except queue.Empty:
            pass
        try:
            while True:
                ok, message = self.events.get_nowait()
                self.busy = False
                self.refresh()
                self.status.set((tr('Finished: ') if ok else tr('Could not finish: ')) + message)
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
                        self.status.set(tr('Could not remember game folder: ') + str(error))
                self.refresh()
            self.wizard_app = None
        if self.game and self.game.poll() is not None:
            code = self.game.returncode
            self.game = None
            self.status.set(tr('Game closed.') if code == 0 else tr('Game exited with code ') + f'{code}' + tr('. Check the game’s logs folder.'))
            self.refresh()
        self.update_states()
        self.later(500, self.poll)

    def close(self):
        if self.busy:
            self.status.set(tr('Wait for the current operation to finish, or cancel the update, before closing.'))
            return
        if self.wizard and self.wizard.winfo_exists():
            self.wizard.lift()
            self.status.set(tr('Close the Setup / Update window first.'))
            return
        self.root.destroy()
