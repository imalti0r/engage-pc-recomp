"""Published updates: metadata checks are automatic; installation requires a user action."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import zipfile
from urllib.parse import quote
from urllib.request import Request, urlopen

RELEASES_API = 'https://api.github.com/repos/imalti0r/engage-pc-recomp/releases?per_page=20'
RELEASES_PAGE = 'https://github.com/imalti0r/engage-pc-recomp/releases/tag/'
VERSION = re.compile(r'^(?:engage-)?v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*))?$')


def version_key(value):
    match = VERSION.fullmatch(value)
    if not match:
        return None
    pre = match[4]
    identifiers = tuple((0, int(part)) if part.isdecimal() else (1, part) for part in pre.split('.')) if pre else ()
    return int(match[1]), int(match[2]), int(match[3]), pre is None, identifiers


@dataclass(frozen=True)
class Update:
    version: str
    page_url: str
    file_name: str = ''


def download_url(tag, name):
    """A release asset's address: GitHub serves assets from a per-tag path."""
    return f'https://github.com/imalti0r/engage-pc-recomp/releases/download/{quote(tag, safe="")}/{quote(name, safe="")}'


def asset_names(version):
    """The names a release may give its setup ZIP: versioned (GitLab style) or plain (GitHub style)."""
    return {f'Engage-Setup-{version}-windows.zip', 'Engage-Setup-windows.zip',
            f'Engage-Launcher-{version}-windows.zip', 'Engage-Launcher-windows.zip'}


def select_update(current, releases):
    installed = version_key(current)
    if installed is None or not isinstance(releases, list):
        raise ValueError('Invalid release version or response.')
    newest = None
    for release in releases:
        if not isinstance(release, dict) or release.get('upcoming_release') or release.get('draft'):
            continue
        tag = release.get('tag_name', '')
        if not isinstance(tag, str) or len(tag) > 100:
            continue
        candidate = version_key(tag)
        if candidate is None or candidate <= installed or (installed[3] and not candidate[3]):
            continue
        version = tag.removeprefix('engage-').removeprefix('v')
        expected = asset_names(version)
        assets = release.get('assets', {})
        # GitLab: {"links": [{"name": …}]}; GitHub: [{"name": …, "browser_download_url": …}]
        links = assets.get('links', []) if isinstance(assets, dict) else assets
        if not isinstance(links, list):
            continue
        package = next((link['name'] for link in links if isinstance(link, dict) and link.get('name') in expected), None)
        if not package:
            continue  # Source-only releases do not update a player's launcher.
        if newest is None or candidate > newest[0]:
            newest = candidate, Update(version, RELEASES_PAGE + quote(tag, safe=''), package)
    return newest[1] if newest else None


def check_for_update(current):
    request = Request(RELEASES_API, headers={'User-Agent': 'Engage-PC-Recomp/' + current,
                                           'Accept': 'application/vnd.github+json'})
    with urlopen(request, timeout=8) as response:
        data = response.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise ValueError('Release response is too large.')
    return select_update(current, json.loads(data))


class Cancelled(Exception):
    pass


def package_name(version):
    if version_key(version) is None:
        raise ValueError('Invalid update version.')
    return f'Engage-Setup-{version}-windows'


def validate_update(info):
    tag = info.page_url.removeprefix(RELEASES_PAGE)
    if not info.page_url.startswith(RELEASES_PAGE) or version_key(tag) != version_key(info.version):
        raise ValueError('The update is not an official project release.')
    if info.file_name not in asset_names(info.version):
        raise ValueError('Unexpected update package name.')


def prepare_update(info, current_root, progress, cancel):
    """Verify and unpack into a new sibling folder; leave the running bundle untouched."""
    validate_update(info)
    current_root = Path(current_root).resolve()
    parent = current_root.parent
    tag = info.page_url.removeprefix(RELEASES_PAGE)
    def check_cancel():
        if cancel.is_set():
            raise Cancelled('Update cancelled. Your current version is unchanged.')
    def request(url):
        return urlopen(Request(url, headers={'User-Agent': 'Engage-PC-Recomp-Updater', 'Accept': '*/*'}), timeout=15)
    check_cancel()
    progress(0, 0, 'Reading update checksum…')
    with request(download_url(tag, 'SHA256SUMS')) as response:
        checksums = response.read(128 * 1024 + 1)
    if len(checksums) > 128 * 1024:
        raise ValueError('The update checksum list is invalid.')
    wanted = None
    for line in checksums.decode('utf-8-sig').splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip('*') == info.file_name and re.fullmatch('[0-9a-fA-F]{64}', parts[0]):
            wanted = parts[0].lower()
    if not wanted:
        raise ValueError('This release has no checksum for its setup ZIP. The current version was kept.')
    with tempfile.TemporaryDirectory(prefix='.engage-update-', dir=parent) as temp:
        stage = Path(temp).resolve()
        if stage.parent != parent:
            raise ValueError('Unexpected update staging directory.')
        archive_path = stage / 'download.zip'
        digest, done = hashlib.sha256(), 0
        with request(download_url(tag, info.file_name)) as response, archive_path.open('xb') as out:
            total = int(response.headers.get('Content-Length') or 0)
            if total > 2 * 1024 ** 3:
                raise ValueError('This update package is too large.')
            while True:
                check_cancel()
                block = response.read(1024 * 1024)
                if not block:
                    break
                done += len(block)
                if done > 2 * 1024 ** 3:
                    raise ValueError('This update package is too large.')
                out.write(block)
                digest.update(block)
                progress(done, total, 'Downloading update…')
        if digest.hexdigest() != wanted or (total and done != total):
            raise ValueError('Update verification failed. Your current version is unchanged.')
        check_cancel()
        progress(0, 0, 'Verifying and extracting update…')
        extracted = stage / 'files'
        extracted.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            size = sum(item.file_size for item in members)
            if len(members) > 100000 or size > 8 * 1024 ** 3 or size + 100 * 1024 ** 2 > shutil.disk_usage(stage).free:
                raise ValueError('The update needs more disk space or contains too many files.')
            for item in members:
                path = PurePosixPath(item.filename)
                if path.is_absolute() or not path.parts or '\\' in item.filename or \
                   any(part in ('.', '..') or ':' in part or part.rstrip(' .') != part for part in path.parts) or \
                   stat.S_ISLNK(item.external_attr >> 16) or item.external_attr & 0x400:
                    raise ValueError('The update ZIP contains an unsafe path or link.')
            for i, item in enumerate(members):
                check_cancel()
                target = extracted.joinpath(*PurePosixPath(item.filename).parts)
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(item) as src, target.open('xb') as out:
                        while block := src.read(1024 * 1024):
                            check_cancel()
                            out.write(block)
                if i % 64 == 0:
                    progress(i, len(members), 'Extracting update…')
        folders = list(extracted.iterdir())
        if len(folders) != 1 or not folders[0].is_dir():
            raise ValueError('The update does not contain one setup folder.')
        package = folders[0]
        required = ('VERSION', 'Engage-Launcher.exe', 'python/python.exe', 'python/pythonw.exe', 'engage_setup/gui.py')
        if any(not (package / name).is_file() for name in required) or (package / 'VERSION').read_text().strip() != info.version:
            raise ValueError('The update is incomplete or has the wrong version.')
        check_cancel()
        target = parent / package_name(info.version)
        for suffix in range(100):
            target = parent / (package_name(info.version) + (f'-{suffix}' if suffix else ''))
            if not target.exists():
                break
        else:
            raise ValueError('Too many update folders already exist.')
        if target.resolve().parent != parent or package.resolve().parent != extracted:
            raise ValueError('Unexpected update destination.')
        package.rename(target)
    return target


def activate_update(current_root, target):
    """Old shortcuts follow the new verified installation, retaining the old files."""
    root, target = Path(current_root).resolve(), Path(target).resolve()
    version = (target / 'VERSION').read_text().strip()
    if target.parent != root.parent or not target.name.startswith(package_name(version)):
        raise ValueError('Unexpected update folder.')
    current = version_key((root / 'VERSION').read_text().strip())
    if current is None or version_key(version) <= current:
        raise ValueError('The update is not newer than this launcher.')
    entry = target / 'Engage-Launcher.exe'
    value = {'version': version, 'root': str(target), 'entry_sha256': hashlib.sha256(entry.read_bytes()).hexdigest()}
    fd, name = tempfile.mkstemp(prefix='.launcher-update-', dir=root)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream)
        os.replace(name, root / 'launcher-update.json')
    finally:
        Path(name).unlink(missing_ok=True)


def redirect_target(current_root):
    root = Path(current_root).resolve()
    marker = root / 'launcher-update.json'
    if not marker.is_file() or marker.stat().st_size > 16384:
        return None
    try:
        record = json.loads(marker.read_text(encoding='utf-8'))
        target = Path(record['root']).resolve()
        version = (target / 'VERSION').read_text().strip()
        current = version_key((root / 'VERSION').read_text().strip())
        if target.parent != root.parent or not target.name.startswith(package_name(version)) or \
           version != record['version'] or current is None or version_key(version) <= current:
            return None
        entry = target / 'Engage-Launcher.exe'
        if hashlib.sha256(entry.read_bytes()).hexdigest() != record['entry_sha256']:
            return None
        return entry
    except (OSError, ValueError, KeyError, TypeError):
        return None
