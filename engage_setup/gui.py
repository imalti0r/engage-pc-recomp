"""Engage's form on the MIT-licensed TotK installer window and process controller."""
import argparse
import os
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, ttk, messagebox

from installer.gui import App as BaseApp, fix_tcl_paths
from .model import Catalog, FIELDS, Form, layout


class App(BaseApp):
    catalog_type = Catalog
    ui_languages = ()
    icon_name = 'engage-setup.ico'

    def build_form(self):
        for name in FIELDS[3:]:
            self.vars[name] = tk.StringVar()
        frame = super().build_form()
        grid = self.form_rows['base'].master
        # The combined XCI row goes first: with it set, the base, update and DLC rows below may stay
        # empty. Rows 0-2 hold base/update/keys, 3 the game language and 4 the install folder; they
        # shift to make room, and the firmware folder lands after keys.
        for widget in grid.grid_slaves():
            row = int(widget.grid_info()['row'])
            widget.grid_configure(row=row + (2 if row >= 3 else 1))
        self.label(grid, 'ui.xci').grid(row=0, column=0, sticky='w', padx=(0, 10), pady=4)
        ttk.Entry(grid, textvariable=self.vars['xci']).grid(row=0, column=1, sticky='ew', pady=4)
        self.button(grid, 'ui.browse', lambda: self.pick_file('xci', 'ui.pick_xci')).grid(row=0, column=2, padx=(8, 0))
        self.vars['xci'].trace_add('write', lambda *_: self.refresh_form())
        self.label(grid, 'ui.firmware').grid(row=4, column=0, sticky='w', padx=(0, 10), pady=4)
        ttk.Entry(grid, textvariable=self.vars['firmware']).grid(row=4, column=1, sticky='ew', pady=4)
        self.button(grid, 'ui.browse', lambda: self.pick_file('firmware', 'ui.firmware')).grid(row=4, column=2, padx=(8, 0))
        extra = ttk.LabelFrame(frame, text='Optional extras', padding=8)
        extra.pack(fill='x', before=self.update_hint, pady=(10, 0))
        extra.columnconfigure(1, weight=1)
        for row, name in enumerate(name for name in FIELDS[4:] if name != 'xci'):
            self.label(extra, 'ui.' + name).grid(row=row, column=0, sticky='w', padx=(0, 10), pady=4)
            ttk.Entry(extra, textvariable=self.vars[name]).grid(row=row, column=1, sticky='ew', pady=4)
            self.button(extra, 'ui.browse', lambda n=name: self.pick_file(n, 'ui.' + n)).grid(
                row=row, column=2, padx=(8, 0))
        return frame

    def form(self):
        return Form(**{name: self.vars[name].get() for name in (*FIELDS, 'dest')}, lang=self.selected_lang())

    def refresh_form(self):
        super().refresh_form()
        form = self.form()
        update = form.finished()
        if update:
            self.update_hint.configure(text=self.cat('ui.update_ready'))
        elif form.xci.strip():
            self.update_hint.configure(text=self.cat('ui.xci_note'))
        self.start_button.configure(text=self.cat('ui.update_start' if update else 'ui.start'))

    def pick_file(self, name, pick_id):
        if name == 'firmware':
            path = filedialog.askdirectory(parent=self.root, title='Choose the extracted firmware NCA folder')
        elif name == 'title_keys':
            path = filedialog.askopenfilename(parent=self.root, title='Choose title.keys', filetypes=[('Keys', '*.keys')])
        else:
            return super().pick_file(name, pick_id)
        if path:
            self.vars[name].set(os.path.normpath(path))

    def build_finish(self):
        frame = super().build_finish()
        self.play_button = self.button(frame, 'ui.play', self.play)
        self.play_button.pack(anchor='e', pady=(12, 0))
        return frame

    def refresh_finish(self):
        super().refresh_finish()
        self.play_button.configure(state='normal' if self.model.result == 'ok' else 'disabled')
        if self.model.result == 'ok' and not self.layout.dev and not getattr(self, 'handoff_scheduled', False):
            self.handoff_scheduled = True
            self.root.after_idle(self.open_installed_launcher)

    def open_installed_launcher(self):
        try:
            from .installed_launcher import open_installed
            open_installed(self.model.dest)
        except OSError as error:
            messagebox.showerror('Launcher could not start',
                'Setup finished. Open Engage-Launcher.exe in your game folder.\n\n' + str(error), parent=self.root)
            return
        getattr(self, 'on_installed', self.root.destroy)()

    def play(self):
        from pathlib import Path
        dest = Path(self.model.dest)
        try:
            from .launcher import launch_game
            launch_game(dest)
        except OSError as error:
            messagebox.showerror('Engage could not start', str(error), parent=self.root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selftest', action='store_true')
    parser.add_argument('--setup', action='store_true', help='Open the setup wizard directly')
    parser.add_argument('--dest', help='Select an existing game installation')
    parser.add_argument('--shots', help='Write launcher screenshots during --selftest (requires Pillow)')
    parser.add_argument('--apply-update', action='store_true', help='Finish a user-approved update of the selected install')
    parser.add_argument('--setup-complete', action='store_true', help='Show where to launch the installed game')
    args = parser.parse_args()
    paths = layout()
    if not paths.dev and not args.selftest:
        from .updates import redirect_target
        target = redirect_target(paths.root)
        if target:
            subprocess.Popen([str(target), *sys.argv[1:]], cwd=target.parent)
            return
    # before Tk exists: keeps the windows sharp on a scaled display
    from .dpi import enable as dpi_enable
    dpi_enable()
    fix_tcl_paths()
    root = tk.Tk()
    from .dpi import apply as dpi_apply
    dpi_apply(root)
    if args.setup:
        app = App(root, 'en', paths)
        if args.dest:
            app.vars['dest'].set(args.dest)
    else:
        try:
            from .launcher_gui import Launcher
            app = Launcher(root, paths, args.dest, remember=not args.selftest, apply_update=args.apply_update)
            if args.setup_complete and not args.selftest:
                message = ('Setup is complete. You can delete the original extracted setup folder.\n\n'
                           'From now on, open Engage-Launcher.exe in your game folder to play, change settings or run Setup / Update.\n\n'
                           f'Game folder: {app.dest}')
                app.status.set('Setup complete. Use Engage-Launcher.exe in your game folder. The original extracted setup folder can be deleted.')
                root.after_idle(lambda: messagebox.showinfo('Setup complete', message, parent=root))
        except (ImportError, OSError, RuntimeError) as error:
            messagebox.showerror('Launcher could not start',
                'Extract the entire setup ZIP, keeping its files together, then try again.\n\n' + str(error), parent=root)
            root.destroy()
            return
    if args.selftest:
        if args.shots and not args.setup:
            from pathlib import Path
            from PIL import ImageGrab
            output = Path(args.shots)
            output.mkdir(parents=True, exist_ok=True)
            pages = iter(app.pages)
            def capture():
                try:
                    page = next(pages)
                except StopIteration:
                    root.destroy()
                    return
                app.show(page)
                def shot():
                    x, y = root.winfo_rootx(), root.winfo_rooty()
                    ImageGrab.grab(bbox=(x, y, x + root.winfo_width(), y + root.winfo_height())).save(output / f'launcher-{page}.png')
                    root.after(200, capture)
                root.after(150, shot)
            root.after(600, capture)
        else:
            root.after(1500, root.destroy)
    root.mainloop()


if __name__ == '__main__':
    main()
