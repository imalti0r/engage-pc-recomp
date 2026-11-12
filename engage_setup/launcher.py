"""Launcher operations over an existing install; game files are never repacked."""
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import stat
import tempfile
import zipfile

TITLE = '0100A6301214E000'
WRAPPERS = ('', TITLE + '/', 'contents/' + TITLE + '/', 'atmosphere/contents/' + TITLE + '/')
SETTINGS = {
    # The order follows the in-game F1 tabs, Screen first (runtime/ui/menu.cpp tab_screen), then Game and Sound, so a
    # player finds a setting where they last saw it.
    'fullscreen': ('display', 'Window mode', '0', {'0': 'Windowed', '1': 'Fullscreen'}),
    # Engage: the window size IS the game resolution (runtime/resolution.c engage_apply), so there is no separate
    # game-resolution setting here: the in-game Screen tab has no such row either.
    'window_size': ('display', 'Window size', '1920x1080', {v: v for v in ('1280x720', '1600x900', '1920x1080', '2560x1440', '3200x1800', '3840x2160')}),
    'vk_present': ('display', 'Presentation', 'fifo', {'fifo': 'VSync', 'mailbox': 'Mailbox', 'immediate': 'Immediate'}),
    'perf_overlay': ('display', 'Performance overlay', 'off', {'off': 'Off', 'fps': 'FPS only', 'full': 'Full'}),
    'render_scale': ('display', '3D render scale', 'game', None),   # free text: "game" or 25..200 (launcher.py render_scale_text)
    'upscaler': ('display', 'Scaling to the window', 'fsr', {'fsr': 'AMD FSR 1', 'bilinear': 'Bilinear', 'dlss': 'NVIDIA DLSS'}),
    'dlss_mode': ('display', 'DLSS mode', 'dlaa',
                  {'dlaa': 'DLAA', 'quality': 'Quality', 'balanced': 'Balanced', 'performance': 'Performance',
                   'ultra': 'Ultra performance'}),
    'sharpness': ('display', 'FSR sharpness', '80', {str(v): str(v) + '%' for v in range(0, 101, 5)}),
    'aspect': ('display', 'Picture shape', 'fit', {'fit': 'Black bars', 'stretch': 'Stretch'}),
    'fps_limit': ('frame rate', 'Frame rate limit', '60', {'30': '30 FPS', '60': '60 FPS'}),
    'lang': ('language', 'Game language', 'en-US', {'en-US': 'English', 'ja': 'Japanese', 'fr': 'French', 'de': 'German', 'it': 'Italian', 'es': 'Spanish', 'ko': 'Korean', 'zh-Hans': 'Chinese (simplified)', 'zh-Hant': 'Chinese (traditional)'}),
    'volume': ('audio', 'Volume', '100', {str(v): str(v) + '%' for v in range(0, 101, 10)}),
}
# Rows that only exist for one upscaler, as the in-game Screen tab shows them: a DLSS mode for an upscaler that does
# not run is noise, and FSR's sharpness means nothing while DLSS produces the picture.
SETTINGS_NEEDS = {
    'dlss_mode': ('upscaler', ('dlss',)),
    'sharpness': ('upscaler', ('fsr', 'bilinear')),
    'render_scale': ('upscaler', ('fsr', 'bilinear')),   # DLSS's mode sets the render ratio instead
}
# The 3D render scale is typed rather than picked: "game" keeps Engage's own choice, a number is a percentage. The
# same limits as the runtime (runtime/resolution.c engage_apply clamps to them) so the launcher cannot write a value
# the game would silently ignore.
RENDER_SCALE_MIN, RENDER_SCALE_MAX = 25, 200


def render_scale_text(value):
    """The 3D render scale as the field shows it: "game" or "<n>%"."""
    if value == 'game':
        return 'Game default'
    return value + '%'


def render_scale_value(text):
    """The ini value for what the player typed: "game" or a whole percentage inside the limits (or None if invalid)."""
    text = text.strip().lower().removeprefix('game default').removesuffix('%').strip()
    if not text or text.startswith('game'):
        return 'game'
    try:
        number = int(round(float(text)))
    except ValueError:
        return None
    if not RENDER_SCALE_MIN <= number <= RENDER_SCALE_MAX:
        return None
    return str(number)
LINE = re.compile(r'^\s*(?:totk_)?([a-z0-9_]+)\s*=\s*(.*?)\s*$', re.I)


def row_visible(key, values):
    """Whether a settings row belongs on the page for the current values (SETTINGS_NEEDS)."""
    need = SETTINGS_NEEDS.get(key)
    return not need or values.get(need[0]) in need[1]


def version_label(version, channel):
    return ('DEV · ' if channel == 'dev' else 'v') + version.removeprefix('v')


def launch_game(dest):
    dest = Path(dest)
    process = subprocess.Popen([str(dest / 'engage.exe')], cwd=dest,
                               env=dict(os.environ, TOTK_LAUNCH_FOREGROUND='1'))
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        allow = ctypes.windll.user32.AllowSetForegroundWindow
        allow.argtypes, allow.restype = [wintypes.DWORD], wintypes.BOOL
        allow(process.pid)
    return process


def read_settings(dest):
    path = Path(dest) / 'engage.ini'
    text = path.read_text(encoding='utf-8-sig') if path.exists() else ''
    values = {}
    for line in text.splitlines():
        match = LINE.match(line)
        if match and match[2]:
            values[match[1].lower()] = match[2].strip('"')
    return values


def write_settings(dest, changes):
    """Change only requested keys, preserving comments and unrelated settings."""
    path = Path(dest) / 'engage.ini'
    if path.is_symlink():
        raise ValueError('engage.ini is a link. Use a regular settings file.')
    text = path.read_text(encoding='utf-8-sig') if path.exists() else ''
    lines = text.splitlines()
    # DLSS decides what the game draws by its mode's ratio, so it pins the 3D render scale at 100 %: a percentage
    # there would multiply with the mode (Performance at 50 % is a quarter of the game resolution). The runtime
    # enforces the same (resolution.c engage_apply).
    if changes.get('upscaler') == 'dlss':
        changes = {**changes, 'render_scale': '100'}
    for key, value in changes.items():
        if key != 'mods_disabled':
            if key not in SETTINGS:
                raise ValueError('Choose a supported value for ' + key)
            choices = SETTINGS[key][3]
            if choices is None:
                # a free-text row: normalize it through its validator, which refuses what the game would ignore
                if key == 'render_scale':
                    normalized = render_scale_value(value)
                    if normalized is None:
                        raise ValueError(f'3D render scale must be Game default or {RENDER_SCALE_MIN}–'
                                         f'{RENDER_SCALE_MAX} %.')
                    value = normalized
            elif value not in choices:
                raise ValueError('Choose a supported value for ' + key)
        if any(c in value for c in '\r\n'):
            raise ValueError('A setting must fit on one line.')
        matches = [i for i, line in enumerate(lines) if (m := LINE.match(line)) and m[1].lower() == key]
        if matches:
            lines[matches[-1]] = f'{key} = {value}'
        else:
            section = 'mods' if key == 'mods_disabled' else SETTINGS[key][0]
            heading = next((i for i, line in enumerate(lines) if line.strip().lower() == f'[{section}]'), None)
            if heading is None:
                lines += ['', f'[{section}]', f'{key} = {value}']
            else:
                lines.insert(heading + 1, f'{key} = {value}')
    fd, temp = tempfile.mkstemp(prefix='.engage-settings-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write('\n'.join(lines) + '\n')
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def linked(path):
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def regular_directory(path):
    return path.is_dir() and not linked(path)


def romfs_root(folder):
    for wrapper in WRAPPERS:
        candidate = folder / (wrapper + 'romfs')
        if all(regular_directory(parent) for parent in (candidate, *candidate.parents)
               if parent == folder or folder in parent.parents):
            return candidate
    return None


def tree_files(root):
    def unreadable(error):
        raise error
    for base, dirs, files in os.walk(root, followlinks=False, onerror=unreadable):
        for name in dirs + files:
            path = Path(base) / name
            if linked(path) or ':' in name or '\\' in name or len(str(path).encode('utf-8')) >= 2099:
                raise ValueError('Linked files or invalid/long paths are not supported.')
        for name in files:
            path = Path(base) / name
            if not stat.S_ISREG(path.stat().st_mode):
                raise ValueError('A mod contains a non-regular file.')
            yield path


@dataclass
class Mod:
    name: str
    enabled: bool
    files: int = 0
    conflicts: int = 0
    problem: str = ''
    code: bool = False


def list_mods(dest):
    root = Path(dest) / 'mods'
    if not root.exists():
        return []
    if not regular_directory(root):
        raise ValueError('The mods folder must be a regular directory.')
    disabled = read_settings(dest).get('mods_disabled', '').split(',')
    result, claimed = [], set()
    folders = sorted(root.iterdir(), key=lambda p: (p.name.encode().lower(), p.name.encode()))
    for folder in folders:
        if not folder.is_dir() and not linked(folder):
            continue
        m = Mod(folder.name, folder.name.encode('utf-8').hex() not in disabled)
        result.append(m)
        try:
            if linked(folder):
                raise ValueError('Linked mod folders are not supported.')
            romfs = romfs_root(folder)
            m.code = any((folder / (prefix + 'exefs')).is_dir() for prefix in WRAPPERS)
            if not romfs:
                raise ValueError('Code-only mod; executable patches are unsupported.' if m.code else 'No romfs folder. Extract each mod into mods/<name>/romfs/.')
            paths = {p.relative_to(romfs).as_posix() for p in tree_files(romfs)}
            m.files = len(paths)
            if m.enabled:
                m.conflicts = len(paths & claimed)
                claimed.update(paths)
        except (OSError, ValueError) as error:
            m.problem = str(error)
    return result


def set_mod_enabled(dest, name, enabled):
    mods = {m.name: m for m in list_mods(dest)}
    if name not in mods or mods[name].problem:
        raise ValueError('This mod cannot be enabled. Check its folder layout.')
    value = read_settings(dest).get('mods_disabled', '')
    token = name.encode('utf-8').hex()
    tokens = [s for s in value.split(',') if s and s != token]
    if not enabled:
        tokens.append(token)
    write_settings(dest, {'mods_disabled': ','.join(tokens)})


def import_mod(dest, source):
    """Import an extracted mod or ZIP; never overwrite a mod already installed."""
    mods = Path(dest) / 'mods'
    mods.mkdir(exist_ok=True)
    if not regular_directory(mods):
        raise ValueError('The mods folder must be a regular directory.')
    source = Path(source).resolve()
    if source == mods.resolve() or mods.resolve() in source.parents or source in mods.resolve().parents:
        raise ValueError('Choose a mod outside this installation.')
    with tempfile.TemporaryDirectory(prefix='.mod-import-', dir=dest) as temp:
        stage = Path(temp)
        if source.is_file():
            with zipfile.ZipFile(source) as archive:
                total, members = 0, archive.infolist()
                if len(members) > 100000:
                    raise ValueError('This ZIP contains too many files. Extract and import a mod folder.')
                for member in members:
                    path = PurePosixPath(member.filename)
                    mode = member.external_attr >> 16
                    if path.is_absolute() or any(p in ('..', '.') or ':' in p or '\\' in p for p in path.parts) or stat.S_ISLNK(mode):
                        raise ValueError('The ZIP contains an unsafe path or link.')
                    total += member.file_size
                    if total > 4 * 1024 ** 3:
                        raise ValueError('This ZIP is too large for launcher import. Extract and import a mod folder.')
                    target = stage.joinpath(*path.parts)
                    if member.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(member) as src, target.open('xb') as out:
                            shutil.copyfileobj(src, out)
            candidate = stage
            name = source.stem
            if not romfs_root(candidate):
                children = [p for p in stage.iterdir() if p.is_dir()]
                if len(children) != 1:
                    raise ValueError('Choose a ZIP containing one mod with a romfs folder.')
                candidate, name = children[0], children[0].name
        else:
            if not regular_directory(source):
                raise ValueError('Choose a regular mod folder or ZIP.')
            list(tree_files(source))
            candidate, name = stage / source.name, source.name
            shutil.copytree(source, candidate)
        romfs = romfs_root(candidate)
        if not romfs:
            raise ValueError('No RomFS files found. Code patches and Cobalt plugins are unsupported.')
        list(tree_files(candidate))
        target = mods / name
        if target.exists():
            raise ValueError('A mod with this folder name already exists. Keep it or remove it manually before importing.')
        # Move only this mod, never staging metadata or user data.
        candidate.rename(target)
    return target


def backup_saves(dest):
    profile = Path(dest) / 'profile'
    sources = [profile / name for name in ('save', 'save-tx') if (profile / name).is_dir()]
    if not sources:
        raise ValueError('No saves yet. Save in-game once before creating a backup.')
    files = []
    for folder in sources:
        if linked(folder):
            raise ValueError('The save folder is a link. Back it up manually.')
        files += list(tree_files(folder))
    backups = Path(dest) / 'save-backups'
    backups.mkdir(exist_ok=True)
    if not regular_directory(backups):
        raise ValueError('The backup folder must be a regular directory.')
    path = backups / (datetime.now().strftime('Engage-%Y%m%d-%H%M%S-%f') + '.zip')
    try:
        with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
            for file in files:
                archive.write(file, file.relative_to(profile).as_posix())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path
