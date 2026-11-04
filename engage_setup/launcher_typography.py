"""Use the runtime menu's licensed Roboto face for launcher interface text."""
import os
from pathlib import Path

UI_FONT = 'Roboto Medium'


def load_ui_font(runtime):
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        add = ctypes.windll.gdi32.AddFontResourceExW
        add.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
        add.restype = ctypes.c_int
        font = Path(runtime) / 'ui/fonts/Roboto-Medium.ttf'
        if not add(str(font.resolve()), 0x10, None):  # FR_PRIVATE: this process only
            raise RuntimeError('The launcher font is missing. Extract the entire setup bundle again.')
    return UI_FONT
