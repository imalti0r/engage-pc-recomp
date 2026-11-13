"""Image-backed native buttons: the approved finish with normal Tk focus and input."""
import math
import tkinter as tk
from tkinter import font as tkfont
from PIL import Image, ImageDraw, ImageTk
from .launcher_typography import UI_FONT

BG = '#091426'


class Pill(tk.Label):
    def __init__(self, parent, text):
        font = (UI_FONT, 9)
        width = tkfont.Font(font=font).measure(text) + 24
        image = Image.new('RGB', (width * 3, 29 * 3), BG)
        ImageDraw.Draw(image).rounded_rectangle((1, 1, width * 3 - 2, 29 * 3 - 2), radius=5 * 3,
                                                fill='#1d2c40', outline='#526075', width=3)
        self.background = ImageTk.PhotoImage(image.resize((width, 29), Image.Resampling.LANCZOS))
        super().__init__(parent, text=text, image=self.background, compound='center',
                         font=font, bg=BG, fg='#d1d7e0', borderwidth=0)


class Button(tk.Button):
    def __init__(self, parent, *, text, command, width=120, height=36, gold=False, icon=None, plain=False):
        self.gold, self.icon, self.size, self.plain = gold, icon, (width, height), plain
        self.min_width = width
        super().__init__(parent, text=text, command=command, compound='center', relief='flat',
                         borderwidth=0, highlightthickness=1, highlightbackground=BG,
                         highlightcolor='#ecc254', bg=BG, activebackground=BG,
                         fg=BG if gold else '#eee9dd', activeforeground=BG if gold else '#fff',
                         disabledforeground='#798395', font=('Georgia', 20, 'bold') if gold else (UI_FONT, 11))
        self.fit_text()
        self.make_images()
        self.bind('<Enter>', lambda _: self.paint(True))
        self.bind('<Leave>', lambda _: self.paint(False))

    def fit_text(self):
        """Widen the button when its wording does not fit. The widths are tuned for English; a translated label
        (Chinese is set in a wider face at the same size) would otherwise be cut off."""
        measured = tkfont.Font(font=self['font']).measure(self['text'])
        room = self.min_width - (58 if self.icon else 34)
        self.size = (max(self.min_width, measured + (58 if self.icon else 34)), self.size[1])
        return room

    def make_images(self):
        w, h = self.size
        self.images = {}
        scale = 3
        label = tkfont.Font(font=self['font']).measure(self['text'])
        for state in ('normal', 'hover', 'disabled'):
            image = Image.new('RGB', (w * scale, h * scale), BG)
            fill = Image.new('RGB', image.size)
            draw = ImageDraw.Draw(fill)
            if self.gold and state != 'disabled':
                top, bottom = ((255, 225, 143), (230, 180, 69)) if state == 'hover' else ((245, 214, 125), (219, 170, 61))
            elif self.plain:
                top = bottom = (9, 20, 38)
            else:
                top = bottom = (23, 39, 60) if state == 'hover' else (10, 22, 39)
            for y in range(h * scale):
                a = y / max(1, h * scale - 1)
                draw.line((0, y, w * scale, y), fill=tuple(round(t * (1 - a) + b * a) for t, b in zip(top, bottom)))
            mask = Image.new('L', image.size)
            ImageDraw.Draw(mask).rounded_rectangle((1, 1, w * scale - 2, h * scale - 2), radius=5 * scale, fill=255)
            image.paste(fill, (0, 0), mask)
            draw = ImageDraw.Draw(image)
            border = '#edd296' if self.gold and state != 'disabled' else '#adbac9' if state == 'hover' else '#8391a3' if state != 'disabled' else '#344156'
            if not self.plain:
                draw.rounded_rectangle((1, 1, w * scale - 2, h * scale - 2), radius=5 * scale, outline=border, width=scale)
            if self.icon:
                x, y = (w - label) / 2 - 25, h / 2
                color = BG if self.gold and state != 'disabled' else '#eee9dd' if state != 'disabled' else '#798395'
                def line(points):
                    draw.line([(int((x + a) * scale), int((y + b) * scale)) for a, b in points], fill=color, width=scale + 1, joint='curve')
                if self.icon == 'play':
                    draw.polygon([(x * scale, (y - 10) * scale), ((x + 15) * scale, y * scale), (x * scale, (y + 10) * scale)], fill=color)
                elif self.icon == 'folder':
                    line([(0, 7), (0, -7), (6, -7), (9, -4), (18, -4), (18, 7), (0, 7)])
                elif self.icon == 'backup':
                    line([(0, -6), (18, -6), (18, 6), (0, 6), (0, -6), (9, -9), (18, -6)])
                    line([(0, -2), (9, 1), (18, -2)])
                    line([(9, 1), (9, 9), (0, 6)])
                    line([(9, 9), (18, 6)])
                elif self.icon == 'settings':
                    points = []
                    for i in range(32):
                        angle = i * math.tau / 32
                        radius = 9 if i % 4 in (0, 1) else 7
                        points.append((9 + math.cos(angle) * radius, math.sin(angle) * radius))
                    line(points + points[:1])
                    draw.ellipse(((x + 6) * scale, (y - 3) * scale, (x + 12) * scale, (y + 3) * scale), outline=color, width=scale)
                elif self.icon == 'download':
                    draw.ellipse((x * scale, (y - 9) * scale, (x + 18) * scale, (y + 9) * scale), outline=color, width=scale)
                    line([(9, -6), (9, 5), (4, 0)])
                    line([(9, 5), (14, 0)])
            self.images[state] = ImageTk.PhotoImage(image.resize((w, h), Image.Resampling.LANCZOS))
        self.built = self.size
        self.paint()

    def paint(self, hover=False):
        state = 'disabled' if self['state'] == 'disabled' else 'hover' if hover else 'normal'
        super().configure(image=self.images[state])

    def configure(self, cnf=None, **kw):
        rebuild = 'text' in kw or 'icon' in kw
        if 'icon' in kw:
            self.icon = kw.pop('icon')
        result = super().configure(cnf, **kw)
        if hasattr(self, 'images'):
            if rebuild:
                self.fit_text()
                self.make_images()
            elif 'state' in kw:
                self.paint()
        return result

    def set_size(self, width, height):
        # the caller's width is the minimum; longer wording still has room
        self.min_width = width
        self.fit_text()
        if getattr(self, 'built', None) != self.size:
            self.size = (self.size[0], height)
            self.make_images()
