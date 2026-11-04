"""The approved launcher home: artwork behind real, keyboard-accessible controls."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageOps, ImageTk
from .launcher_controls import Button
from .launcher_typography import UI_FONT

BG, INK, MUTED, GOLD, LINE = '#091426', '#eee9dd', '#a4afc0', '#ecc254', '#29384a'


class Home(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app, self.pending = app, None
        art = Path(__file__).with_name('art')
        with Image.open(art / 'cathedral.jpg') as image:
            self.scene = image.convert('RGB')
        with Image.open(art / 'title.webp') as image:
            self.wordmark = image.convert('RGBA')
            self.wordmark = self.wordmark.crop(self.wordmark.getbbox())
        summary = ttk.Frame(self, padding=(34, 12), height=121)
        summary.pack(side='bottom', fill='x')
        summary.pack_propagate(False)
        summary.grid_propagate(False)
        self.display = tk.StringVar()
        self.mod_count, self.mod_name = tk.StringVar(), tk.StringVar()
        for i in range(3):
            summary.columnconfigure(i * 2, weight=1, uniform='summary')
        display, mods, saves = [ttk.Frame(summary) for _ in range(3)]
        for i, panel in enumerate((display, mods, saves)):
            panel.grid(row=0, column=i * 2, sticky='nsew', padx=(0 if i == 0 else 22, 0))
            if i:
                ttk.Separator(summary, orient='vertical').grid(row=0, column=i * 2 - 1, sticky='ns', padx=(20, 0))
        for panel, title in ((display, 'Display'), (mods, 'Mods'), (saves, 'Saves')):
            ttk.Label(panel, text=title, style='SummaryHeading.TLabel').pack(anchor='w', pady=(0, 8))
        ttk.Label(display, textvariable=self.display).pack(anchor='w')
        ttk.Button(display, text='Edit settings', style='Link.TButton', command=lambda: app.show('settings')).pack(anchor='w', pady=(8, 0))
        ttk.Label(mods, textvariable=self.mod_count).pack(anchor='w')
        ttk.Label(mods, textvariable=self.mod_name, style='Muted.TLabel', width=30).pack(anchor='w', pady=(2, 4))
        ttk.Button(mods, text='Manage mods', style='Link.TButton', command=lambda: app.show('mods')).pack(anchor='w')
        buttons = ttk.Frame(saves)
        buttons.pack(anchor='w', pady=(4, 0))
        self.open_saves = Button(buttons, text='Open folder', icon='folder', width=145,
                                 command=lambda: app.open_folder('profile/save'))
        self.open_saves.pack(side='left')
        self.backup = Button(buttons, text='Back up', icon='backup', width=125, command=app.backup)
        self.backup.pack(side='left', padx=(10, 0))
        ttk.Separator(self).pack(side='bottom', fill='x')
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        self.play_button = Button(self.canvas, text='Play Engage', command=app.play, gold=True, icon='play', width=377, height=64)
        self.canvas.bind('<Configure>', self.schedule)
        self.bind('<Destroy>', self.on_destroy)
        self.state = None

    def on_destroy(self, event):
        if event.widget == self and self.pending:
            self.after_cancel(self.pending)
            self.pending = None

    def schedule(self, _=None):
        if self.pending:
            self.after_cancel(self.pending)
        self.pending = self.after(35, self.draw)

    def draw(self):
        self.pending = None
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        if w < 2 or h < 2:
            return
        self.canvas.delete('all')
        self.background = ImageTk.PhotoImage(ImageOps.fit(self.scene, (w, h), Image.Resampling.LANCZOS, centering=(.5, .35)))
        self.canvas.create_image(0, 0, image=self.background, anchor='nw')
        left, width = int(w * .038), int(w * .337)
        title = self.wordmark.copy()
        title.thumbnail((int(w * .44), int(h * .52)), Image.Resampling.LANCZOS)
        self.title = ImageTk.PhotoImage(title)
        self.canvas.create_image(left - 35, int(h * .11), image=self.title, anchor='nw')
        y = int(h * .56)
        self.dot = self.canvas.create_oval(left, y - 4, left + 8, y + 4, fill='#80c973', outline='')
        self.status = self.canvas.create_text(left + 19, y, text='', fill=INK, anchor='w', font=(UI_FONT, 11, 'bold'))
        self.canvas.create_line(left + 162, y - 10, left + 162, y + 10, fill='#465266')
        self.canvas.create_text(left + 176, y, text='Game 2.0.0', fill=MUTED, anchor='w', font=(UI_FONT, 11))
        self.play_button.set_size(width, 64)
        self.canvas.create_window(left, int(h * .65), window=self.play_button, anchor='nw', width=width, height=64)
        self.canvas.create_text(left + width // 2, int(h * .65) + 86, text='F1 for in-game settings',
                                fill=INK, font=(UI_FONT, 11, 'italic'))
        if self.state:
            self.set_state(*self.state)

    def set_state(self, ready, running, busy):
        self.state = ready, running, busy
        if hasattr(self, 'status'):
            self.canvas.itemconfigure(self.status, text='Game running' if running else 'Working…' if busy else 'Ready to play' if ready else 'Setup needed')
            self.canvas.itemconfigure(self.dot, fill='#80c973' if ready else GOLD)
        self.backup.configure(state='normal' if ready and not running and not busy else 'disabled')
        self.open_saves.configure(state='normal' if ready else 'disabled')

    def set_summary(self, values, mods):
        self.display.set(f"{values.get('output_res', '1920x1080').replace('x', ' × ')}   ·   {values.get('fps_limit', '60')} FPS")
        enabled = [m for m in mods if m.enabled and not m.problem]
        self.mod_count.set(f'{len(enabled)} enabled')
        self.mod_name.set(enabled[0].name if len(enabled) == 1 else 'Ready for the next launch' if enabled else 'No mods enabled')
