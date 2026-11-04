"""Launcher title bar controls using the OS window, resize frame and taskbar."""
import os
import tkinter as tk
from PIL import Image, ImageDraw, ImageTk

BG = '#091426'


class Chrome:
    def __init__(self, root, header, parent, close):
        self.root = root
        self.pending = None
        self.images = []
        for name, action in (('Minimize', self.minimize), ('Maximize', self.maximize), ('Close', close)):
            image = Image.new('RGB', (84, 64), BG)
            draw = ImageDraw.Draw(image)
            if name == 'Minimize':
                draw.line((30, 34, 54, 34), fill='#eee9dd', width=2)
            elif name == 'Maximize':
                draw.rectangle((31, 22, 53, 44), outline='#eee9dd', width=2)
            else:
                draw.line((31, 22, 53, 44), fill='#eee9dd', width=2)
                draw.line((31, 44, 53, 22), fill='#eee9dd', width=2)
            icon = ImageTk.PhotoImage(image.resize((42, 32), Image.Resampling.LANCZOS))
            self.images.append(icon)
            tk.Button(parent, text=name, image=icon, command=action, bg=BG, activebackground='#243650',
                      borderwidth=0, highlightthickness=1, highlightbackground=BG,
                      highlightcolor='#ecc254', takefocus=True).pack(side='left')
        header.bind('<ButtonPress-1>', self.drag)
        header.bind('<Double-Button-1>', lambda _: self.maximize())
        if os.name == 'nt':
            self.pending = root.after(20, self.install)

    def install(self):
        self.pending = None
        import ctypes
        from ctypes import wintypes
        user = ctypes.windll.user32
        user.GetParent.argtypes, user.GetParent.restype = [wintypes.HWND], wintypes.HWND
        self.hwnd = user.GetParent(self.root.winfo_id())
        get = user.GetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user.GetWindowLongW
        put = user.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user.SetWindowLongW
        get.argtypes, get.restype = [wintypes.HWND, ctypes.c_int], ctypes.c_ssize_t
        put.argtypes, put.restype = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t], ctypes.c_ssize_t
        # Retain the native resize frame, taskbar behavior and system commands.
        put(self.hwnd, -16, get(self.hwnd, -16) & ~0x00C00000)  # WS_CAPTION
        user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        user.SetWindowPos(self.hwnd, None, 0, 0, 0, 0, 0x0027)  # FRAMECHANGED | NOMOVE | NOSIZE | NOZORDER
        self.root.minsize(980, 650)

    def minimize(self):
        self.root.iconify()

    def maximize(self):
        self.root.state('normal' if self.root.state() == 'zoomed' else 'zoomed')

    def drag(self, event):
        if os.name == 'nt' and hasattr(self, 'hwnd'):
            import ctypes
            from ctypes import wintypes
            user = ctypes.windll.user32
            user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user.ReleaseCapture()
            user.SendMessageW(self.hwnd, 0x00A1, 2, 0)  # WM_NCLBUTTONDOWN, HTCAPTION
        else:
            self.root.geometry(f'+{event.x_root - event.x}+{event.y_root - event.y}')
