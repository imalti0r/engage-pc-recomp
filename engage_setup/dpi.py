"""High-DPI support for the setup wizard and the launcher (Windows).

Tk draws in physical pixels. Without the process being DPI aware, Windows pretends the screen is
96 DPI and then bitmap-stretches the window: text turns blurry on a scaled display. Making the
process per-monitor aware keeps every pixel sharp, and then Tk's own scaling (points to pixels) is
set from the monitor's real DPI so the text keeps its apparent size.

    enable()        before tk.Tk(): make this process DPI aware (no-op off Windows)
    apply(root)     after tk.Tk(): set Tk's scaling, return the factor for pixel sizes
"""
import ctypes
import os
import sys

# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
_PER_MONITOR_V2 = ctypes.c_void_p(-4)
_LOG_PIXELS_PER_INCH = 88   # GetDeviceCaps index


def enable():
    """Make the process per-monitor DPI aware. Call before Tk creates its window."""
    if os.name != 'nt':
        return False
    user32 = ctypes.windll.user32
    try:
        # Windows 10 1703 and later: the context call keeps Tk sharp on every monitor
        set_context = user32.SetProcessDpiAwarenessContext
        if set_context(_PER_MONITOR_V2):
            return True
    except (AttributeError, OSError):
        pass
    try:
        # Windows 8.1 and later fallback: per-monitor aware, without the v2 behaviours
        return ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0
    except (AttributeError, OSError):
        pass
    try:
        return bool(user32.SetProcessDPIAware())
    except (AttributeError, OSError):
        return False


def dpi():
    """The primary monitor's DPI (96 at 100 % display scaling)."""
    if os.name != 'nt':
        return 96
    try:
        return int(ctypes.windll.user32.GetDpiForSystem())
    except (AttributeError, OSError):
        pass
    try:
        hdc = ctypes.windll.user32.GetDC(0)
        try:
            return int(ctypes.windll.gdi32.GetDeviceCaps(hdc, _LOG_PIXELS_PER_INCH))
        finally:
            ctypes.windll.user32.ReleaseDC(0, hdc)
    except (AttributeError, OSError):
        return 96


def apply(root):
    """Set Tk's point-to-pixel scaling from the monitor and return the pixel factor (1.0 at 96 DPI).

    Tk reads its scaling as pixels per point; the default matches 72 DPI, which leaves a 150 %
    display with text a third too small once the process is DPI aware.
    """
    value = dpi()
    factor = value / 96.0
    try:
        root.tk.call('tk', 'scaling', value / 72.0)
    except Exception:   # a Tk build without the scaling command: keep its own default
        pass
    if os.name == 'nt':
        # the menu font and the dialog font follow the scaling only when named explicitly
        try:
            import tkinter.font as tkfont
            for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont'):
                font = tkfont.nametofont(name, root)
                font.configure(size=int(round(9 * factor)))
        except Exception:
            pass
    return factor


def scaled(root, size):
    """A pixel size from the design size, scaled for this monitor: (1120, 710) -> (1680, 1065) at 150 %."""
    factor = getattr(root, '_engage_dpi_factor', None)
    if factor is None:
        factor = apply(root)
        root._engage_dpi_factor = factor
    width, height = size
    return int(round(width * factor)), int(round(height * factor))
