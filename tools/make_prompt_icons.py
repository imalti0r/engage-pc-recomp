# Adapted from MacNativeGames games/totk/scripts/make_button_icons.py @ 933b6a0 (MIT, Copyright (c) 2026
# MacNativeGames contributors): drawing the keyboard-and-mouse prompt icons here, at the game's own sprite rectangles,
# so nothing of the game is copied into the repository.
"""Draw the keyboard-and-mouse prompt atlas for Engage's button sprite atlas.

Engage draws every key prompt from one 256x256 sprite atlas (icon/button/button.bundle, and the solid variant in
icon/buttonoutline/button_filled.bundle). Each prompt is a sprite with a fixed rectangle in that atlas, so drawing our
own icons into the same rectangles replaces every prompt at once without touching a prefab, font or message.

The style is measured from the game's own icons, so the two sets read as one family:
  - line art only: a ring or key outline of 3 px on a 40 px cell (7.5 % of the cell), nothing filled;
  - the legend sits at 43 % of the cell's height, with the same thin stroke;
  - the glyph shapes follow the Switch's own iconography: a circle for the face buttons, a wide cap for the
    shoulders, a small cap for the triggers, a cross for the d-pad.

The rectangles below are the game's own sprite layout (plain geometry, no artwork): name, x, y, width, height, in
Unity's bottom-left origin. Icons are drawn at 8x and downsampled, with letters from the project's own font.

Output: runtime/prompt_icons.h, the two atlases as zstd-compressed RGBA8 blobs plus their layout.

    .venv-py314\\Scripts\\python tools/make_prompt_icons.py
"""
import sys
from pathlib import Path

import zstandard
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SIZE = 256
SS = 8                       # supersampling factor
FONT = ROOT / 'runtime/ui/fonts/Roboto-Medium.ttf'
OUT = ROOT / 'runtime/prompt_icons.h'

# The game's sprite rectangles: (name, x, y, w, h) in Unity's bottom-left origin, read from the bundle.
OUTLINE_RECTS = [
    ('A', 44.06, 0.06, 39.89, 39.89), ('B', 0.06, 44.06, 39.89, 39.89),
    ('X', 88.06, 0.06, 39.89, 39.89), ('Y', 44.06, 44.06, 39.89, 39.89),
    ('L', 44.08, 132.08, 39.85, 35.90), ('R', 0.08, 132.08, 39.90, 35.90),
    ('ZL', 132.08, 88.08, 39.85, 39.85), ('ZR', 0.03, 0.08, 39.95, 39.90),
    ('Plus', 88.06, 44.06, 39.89, 39.89), ('Minus', 176.06, 0.08, 39.89, 39.87),
    ('StickL', 176.08, 88.08, 37.85, 37.85), ('StickR', 218.08, 88.08, 37.85, 37.85),
    ('StickRPush', 88.08, 132.03, 33.85, 40.90),
    ('Up', 44.06, 88.06, 39.89, 39.89), ('Down', 88.06, 88.06, 39.89, 39.89),
    ('Left', 0.06, 88.06, 39.89, 39.89), ('Right', 132.06, 0.06, 39.89, 39.89),
    ('Home', 132.06, 44.08, 39.89, 39.87), ('Capture', 176.08, 44.08, 39.85, 39.85),
]
FILLED_RECTS = [
    ('A', 0.00, 0.00, 48.00, 48.00), ('ArrowKey', 52.00, 156.00, 48.00, 48.00),
    ('B', 104.00, 156.00, 48.00, 48.00), ('Capture', 52.00, 0.00, 48.00, 48.00),
    ('Down', 52.00, 52.00, 48.00, 48.00), ('Home', 156.00, 104.00, 48.00, 48.00),
    ('L', 156.00, 207.08, 48.00, 46.90), ('Left', 208.00, 52.00, 48.00, 48.00),
    ('Minus', 0.00, 156.00, 48.00, 48.00), ('Plus', 104.00, 52.00, 48.00, 48.00),
    ('R', 156.00, 156.08, 48.00, 46.90), ('Right', 208.00, 0.00, 48.00, 48.00),
    ('StickL', 0.00, 52.00, 48.00, 48.00), ('StickLPush', 208.08, 156.00, 43.85, 48.00),
    ('StickR', 0.00, 104.00, 48.00, 48.00), ('StickRPush', 208.08, 104.00, 43.85, 48.00),
    ('Up', 156.00, 0.00, 48.00, 48.00), ('X', 104.00, 104.00, 48.00, 48.00),
    ('Y', 156.00, 52.00, 48.00, 48.00), ('ZL', 52.00, 104.00, 48.00, 48.00),
    ('ZR', 104.00, 0.00, 48.00, 48.00),
]

# Measured on the game's own icons (build/measure_style.py): a 40 px cell carries a 3 px outline and a legend whose
# capital letters are 17 px tall. A font's capital height is about 0.7 of its point size, so the size that gives 17 px
# caps is 17/0.7 = 24 px on that 40 px cell: 0.60 of the cell.
STROKE = 3.0 / 40.0          # stroke width as a fraction of the cell's short side
LEGEND = 0.60                # legend point size as a fraction of the cell's short side (17 px caps on 40 px)

# The key or mouse button each Switch button is pressed with (runtime/input_map.c DEFAULT_KEYS).
LABELS = {
    'A': 'E', 'B': 'shift', 'X': 'space', 'Y': 'mouse_l',
    'L': 'Q', 'R': 'R', 'ZL': 'mouse_r', 'ZR': 'F',
    'Plus': 'tab', 'Minus': 'M',
    'StickL': 'wasd', 'StickR': 'mouse_look', 'StickLPush': 'ctrl', 'StickRPush': 'C',
    'Up': '2', 'Down': '4', 'Left': '1', 'Right': '3',
    'Home': 'home', 'Capture': 'prtsc', 'ArrowKey': 'arrow',
}


def box(rect):
    """PIL box (top-left origin) of a Unity rectangle."""
    _, x, y, w, h = rect
    return (x, SIZE - y - h, x + w, SIZE - y)


class Pen:
    """A cell's drawing surface, in supersampled units, with the game's own stroke and legend proportions."""

    def __init__(self, d, rect):
        self.d = d
        x0, y0, x1, y1 = [v * SS for v in box(rect)]
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
        self.w, self.h = x1 - x0, y1 - y0
        self.side = min(self.w, self.h)
        self.stroke = max(1.0, self.side * STROKE)
        self.cx, self.cy = (x0 + x1) / 2, (y0 + y1) / 2

    def inset(self, f=0.0):
        """The cell shrunk by f of its side: the game's icons sit a little inside their rectangle."""
        m = self.side * f
        return self.x0 + m, self.y0 + m, self.x1 - m, self.y1 - m

    def text(self, text, px=None, max_w=None, at=None, ink=255):
        """The legend, in the game's own proportion: it fills most of the cell, as its letters do."""
        size = px if px is not None else self.side * LEGEND
        max_w = max_w if max_w is not None else self.w * 0.70
        while size > 2:
            f = ImageFont.truetype(str(FONT), int(size))
            l, t, r, b = self.d.textbbox((0, 0), text, font=f)
            if (r - l) <= max_w and (b - t) <= self.side * LEGEND * 1.15:
                break
            size *= 0.94
        f = ImageFont.truetype(str(FONT), int(size))
        l, t, r, b = self.d.textbbox((0, 0), text, font=f)
        cx, cy = at if at else (self.cx, self.cy)
        self.d.text((cx - (r - l) / 2 - l, cy - (b - t) / 2 - t), text, font=f, fill=ink)

    def ring(self):
        """The face-button circle: the game's own shape for A, B, X and Y."""
        x0, y0, x1, y1 = self.inset(0.02)
        self.d.ellipse((x0, y0, x1, y1), outline=255, width=int(round(self.stroke)))

    def cap(self, inset=0.0, radius=0.20, text=None, px=None, max_w=None):
        """A rounded key outline with an optional legend, as the shoulders, triggers and keys read."""
        x0, y0, x1, y1 = self.inset(inset)
        self.d.rounded_rectangle((x0, y0, x1, y1), radius=self.side * radius, outline=255,
                                 width=int(round(self.stroke)))
        if text:
            self.text(text, px=px, max_w=max_w)

    def triangle(self, direction, scale=0.30):
        """A solid triangle, as the game draws the d-pad's four directions inside its ring."""
        r = self.side * scale
        dx, dy = {'up': (0, -1), 'down': (0, 1), 'left': (-1, 0), 'right': (1, 0)}[direction]
        tip = (self.cx + dx * r, self.cy + dy * r)
        bx, by = self.cx + dx * r * 0.30, self.cy + dy * r * 0.30
        px, py = -dy, dx
        self.d.polygon([tip, (bx + px * r * 0.62, by + py * r * 0.62), (bx - px * r * 0.62, by - py * r * 0.62)],
                       fill=255)

    def mouse(self, pressed):
        """A mouse from above: outline, the two button seams, the wheel, and the pressed button marked."""
        w, h = self.w * 0.46, self.h * 0.84
        x0, x1 = self.cx - w / 2, self.cx + w / 2
        y0, y1 = self.cy - h / 2, self.cy + h / 2
        r = w * 0.42
        lw = int(round(self.stroke))
        self.d.rounded_rectangle((x0, y0, x1, y1), radius=r, outline=255, width=lw)
        mid = self.cx
        split = y0 + h * 0.42
        self.d.line((x0 + lw, split, x1 - lw, split), fill=255, width=lw)
        self.d.line((mid, y0 + lw, mid, split), fill=255, width=lw)
        # the wheel
        self.d.rounded_rectangle((mid - w * 0.06, y0 + h * 0.18, mid + w * 0.06, y0 + h * 0.34), radius=w * 0.06,
                                 fill=255)
        if pressed in ('left', 'both'):
            self.d.ellipse((x0 + lw * 1.6, y0 + lw * 1.6, mid - lw * 0.9, split - lw * 1.2), fill=255)
        if pressed in ('right', 'both'):
            self.d.ellipse((mid + lw * 0.9, y0 + lw * 1.6, x1 - lw * 1.6, split - lw * 1.2), fill=255)

    def arrows(self, r=0.22):
        """Four small triangles around the mouse: its four directions."""
        for d in ('up', 'down', 'left', 'right'):
            save = (self.cx, self.cy)
            dx, dy = {'up': (0, -1), 'down': (0, 1), 'left': (-1, 0), 'right': (1, 0)}[d]
            self.cx = save[0] + dx * self.w * 0.34
            self.cy = save[1] + dy * self.h * 0.40
            self.triangle(d, self.side * r * 0.5)
            self.cx, self.cy = save

    def shift(self):
        """The Shift symbol: an outline arrow, as keyboards print it."""
        w, h = self.side * 0.20, self.side * 0.16
        cx, cy = self.cx, self.cy
        pts = [(cx, cy - h), (cx + w, cy), (cx + w * 0.46, cy), (cx + w * 0.46, cy + h),
               (cx - w * 0.46, cy + h), (cx - w * 0.46, cy), (cx - w, cy)]
        self.d.line(pts + [pts[0]], fill=255, width=int(round(self.stroke)), joint='curve')

    def wasd(self):
        """A W A S D cluster, each cap as readable as the rest: W above, A S D below."""
        kw, kh = self.w * 0.30, self.h * 0.30
        gap = self.w * 0.035
        top = self.cy - kh - gap / 2
        bot = self.cy + gap / 2
        left = self.cx - (kw * 3 + gap * 2) / 2
        lw = max(1.0, self.side * STROKE * 0.85)
        for cx, cy, ch in ((self.cx, top + kh / 2, 'W'),
                           (left + kw / 2, bot + kh / 2, 'A'),
                           (left + kw + gap + kw / 2, bot + kh / 2, 'S'),
                           (left + (kw + gap) * 2 + kw / 2, bot + kh / 2, 'D')):
            x0, x1 = cx - kw / 2, cx + kw / 2
            y0, y1 = cy - kh / 2, cy + kh / 2
            self.d.rounded_rectangle((x0, y0, x1, y1), radius=kw * 0.18, outline=255, width=int(round(lw)))
            self.text(ch, px=kh * 0.72, max_w=kw * 0.66, at=(cx, cy))


def draw_cell(d, name, rect):
    p = Pen(d, rect)
    label = LABELS.get(name, name.lower())
    # Readability first: every key is a rounded keycap that fills its cell, with the legend large inside it. The game's
    # own rings and caps are 40 px art read at a glance; a ring with a small letter inside is not, and a prompt the
    # player has to squint at is worse than the Switch button it replaces.
    if label == 'mouse_l':
        p.mouse('left')
    elif label == 'mouse_r':
        p.mouse('right')
    elif label == 'mouse_look':
        p.mouse(None)
        p.arrows()
    elif label == 'wasd':
        # Four keycaps cannot be read in one 40 px cell (each would be 12 px). The cell says WASD instead, which is
        # exactly what the player presses.
        p.cap(inset=0.0, text='WASD', max_w=p.w * 0.86)
    elif label == 'shift':
        p.cap(inset=0.0, text='Shift', max_w=p.w * 0.80)
    elif label == 'space':
        p.cap(inset=0.0, text='Space', max_w=p.w * 0.80)
    elif label == 'tab':
        p.cap(inset=0.0, text='Tab', max_w=p.w * 0.78)
    elif label == 'ctrl':
        p.cap(inset=0.0, text='Ctrl', max_w=p.w * 0.78)
    elif label == 'home':
        p.cap(inset=0.0, text='Home', max_w=p.w * 0.82)
    elif label == 'prtsc':
        p.cap(inset=0.0, text='PrtSc', max_w=p.w * 0.84)
    elif label == 'arrow':
        p.cap(inset=0.0, text='\u2191')
    elif name in ('Up', 'Down', 'Left', 'Right'):
        p.cap(inset=0.0, text=label)
    elif name in ('Plus', 'Minus'):
        p.cap(inset=0.0, text=label)
    elif name in ('StickL', 'StickR', 'StickLPush', 'StickRPush'):
        p.cap(inset=0.0, text=label, max_w=p.w * 0.80)
    else:
        # the face buttons and the letter keys: a cap with the key's own legend
        p.cap(inset=0.0, text=label, max_w=p.w * 0.76)


def build(rects, path):
    img = Image.new('L', (SIZE * SS, SIZE * SS), 0)
    d = ImageDraw.Draw(img)
    for rect in rects:
        draw_cell(d, rect[0], rect)
    img = img.resize((SIZE, SIZE), Image.LANCZOS)
    rgba = Image.merge('RGBA', (Image.new('L', img.size, 255), Image.new('L', img.size, 255),
                                Image.new('L', img.size, 255), img))
    rgba.save(path)
    return rgba


def compress(rgba):
    return zstandard.ZstdCompressor(level=19).compress(rgba.tobytes())


def emit(name, rgba, rects):
    blob = compress(rgba)
    rows = []
    for rect in rects:
        x0, y0, x1, y1 = box(rect)
        rows.append(f'    {{"{rect[0]}", {x0:.2f}f, {y0:.2f}f, {x1 - x0:.2f}f, {y1 - y0:.2f}f}},')
    return (f'// {name}: {SIZE}x{SIZE} RGBA8, zstd {len(blob)} bytes of {len(rgba.tobytes())}\n'
            f'static const unsigned char {name}_zstd[] = {{\n' + _hex(blob) + '\n};\n'
            f'static const unsigned {name}_zstd_size = {len(blob)};\n'
            f'static const PromptRect {name}_rects[] = {{\n' + '\n'.join(rows) + '\n};\n'
            f'static const unsigned {name}_count = {len(rects)};\n')


def _hex(blob):
    lines = []
    for i in range(0, len(blob), 16):
        lines.append('    ' + ','.join(str(b) for b in blob[i:i + 16]) + ',')
    return '\n'.join(lines)


def main():
    preview = ROOT / 'build/prompt-icons'
    preview.mkdir(parents=True, exist_ok=True)
    outline = build(OUTLINE_RECTS, preview / 'pc_outline.png')
    filled = build(FILLED_RECTS, preview / 'pc_filled.png')
    header = ('// Generated by tools/make_prompt_icons.py: the keyboard-and-mouse prompt atlases. Do not edit.\n'
              '#pragma once\n\n'
              'typedef struct { const char *name; float x, y, w, h; } PromptRect;\n\n'
              + emit('prompt_pc_outline', outline, OUTLINE_RECTS) + '\n'
              + emit('prompt_pc_filled', filled, FILLED_RECTS))
    OUT.write_text(header, encoding='utf-8')
    print(f'wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size} bytes)')
    print(f'previews in {preview.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
