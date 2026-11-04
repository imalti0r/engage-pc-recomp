"""Keep the packaged launcher and rebuild tools with the player's installation."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile


def installed_game(root):
    root = Path(root).resolve()
    if root.parent.name == '.launcher':
        from .model import installed_state
        game = root.parent.parent
        if installed_state(game):
            return game
    return None


def install_launcher(root, dest):
    root, dest = Path(root).resolve(), Path(dest).resolve()
    manifest = (root / 'setup-inventory.json').read_bytes()
    inventory = json.loads(manifest)
    files = []
    for entry in inventory:
        name = entry['path']
        path = PurePosixPath(name)
        if not name or path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
            raise ValueError('Invalid launcher package inventory path.')
        source = root / name
        if not source.resolve().is_relative_to(root):
            raise ValueError('Launcher package contains a file outside its folder.')
        files.append((name, entry['size'], entry['sha256']))
    required = {'Engage-Launcher.exe', 'python/python.exe', 'python/pythonw.exe', 'engage_setup/gui.py', 'VERSION'}
    if not required.issubset(name for name, _, _ in files):
        raise ValueError('Launcher package is incomplete. Extract the entire setup ZIP and retry.')
    store = dest / '.launcher'
    if store.is_symlink() or store.is_junction():
        raise ValueError('The installed launcher folder is a directory link. Choose another installation folder.')
    store.mkdir(exist_ok=True)
    identity = hashlib.sha256(manifest).hexdigest()
    target = store / identity
    if target.is_symlink() or target.is_junction():
        raise ValueError('The installed launcher package is a directory link.')
    pending = None
    try:
        if target.exists():
            package = target
        else:
            pending = Path(tempfile.mkdtemp(prefix='.install-', dir=store))
            package = pending
        for name, size, expected in files:
            output = package / name
            if not output.resolve().is_relative_to(package.resolve()):
                raise ValueError('Installed launcher contains a file outside its package.')
            if pending:
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(root / name, output)
            if output.stat().st_size != size:
                raise ValueError(f'Launcher package verification failed: {name}. Extract the setup ZIP again.')
            with output.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                    raise ValueError(f'Launcher package verification failed: {name}. Extract the setup ZIP again.')
        if pending:
            (pending / 'setup-inventory.json').write_bytes(manifest)
            pending.rename(target)
            pending = None
        # Versioned packages avoid replacing the Python files used by a running launcher.
        entry = dest / 'Engage-Launcher.exe.new'
        shutil.copy2(target / 'Engage-Launcher.exe', entry)
        os.replace(entry, dest / 'Engage-Launcher.exe')
        marker = dest / 'launcher-current.txt.new'
        marker.write_text(identity, encoding='ascii')
        os.replace(marker, dest / 'launcher-current.txt')
    finally:
        if pending:
            shutil.rmtree(pending)
    return target


def open_installed(dest):
    dest = Path(dest).resolve()
    return subprocess.Popen([str(dest / 'Engage-Launcher.exe'), '--dest', str(dest), '--setup-complete'], cwd=dest)
