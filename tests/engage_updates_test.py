"""Release comparison and network failures do not modify an installation."""
import json
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import zipfile
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engage_setup.updates import (Cancelled, activate_update, check_for_update,
    prepare_update, redirect_target, select_update, version_key)


def release(version, ready=True, upcoming=False, github=False):
    name = f'Engage-Setup-{version}-windows.zip'
    if github:
        return {'tag_name': 'engage-v' + version, 'draft': upcoming,
                'assets': [{'name': name, 'browser_download_url': f'https://github.com/x/y/releases/download/t/{name}'}] if ready else []}
    return {'tag_name': 'engage-v' + version, 'upcoming_release': upcoming,
            'assets': {'links': [{'name': name}] if ready else []}}


class UpdateTest(unittest.TestCase):
    def test_numeric_prerelease_order_and_release_channel(self):
        self.assertGreater(version_key('0.1.0-alpha.10'), version_key('0.1.0-alpha.9'))
        self.assertGreater(version_key('0.1.0'), version_key('0.1.0-rc.10'))
        update = select_update('0.1.0-alpha.5', [release('0.1.0-alpha.9'), release('0.1.0-alpha.10')])
        self.assertEqual(update.version, '0.1.0-alpha.10')
        self.assertIsNone(select_update('1.0.0', [release('2.0.0-alpha.1')]))

    def test_skip_future_source_only_equal_and_unsafe_tags(self):
        self.assertIsNone(select_update('0.1.0-alpha.5', [release('0.1.0-alpha.5'),
            release('1.0.0', ready=False), release('2.0.0', upcoming=True),
            {'tag_name': 'https://elsewhere.example/evil'}]))
        update = select_update('0.1.0-alpha.5', [release('0.1.0-alpha.6')])
        self.assertEqual(update.page_url, 'https://github.com/imalti0r/engage-pc-recomp/releases/tag/engage-v0.1.0-alpha.6')

    def test_github_release_shape_and_plain_asset_name(self):
        # GitHub returns assets as a list and the releases here name the ZIP without a version.
        update = select_update('0.1.0-alpha.12', [release('0.1.0-alpha.13', github=True)])
        self.assertEqual(update.version, '0.1.0-alpha.13')
        self.assertEqual(update.file_name, 'Engage-Setup-0.1.0-alpha.13-windows.zip')
        plain = {'tag_name': 'engage-v0.1.0-alpha.13',
                 'assets': [{'name': 'Engage-Setup-windows.zip', 'browser_download_url': 'https://github.com/x/y/releases/download/t/z.zip'}]}
        self.assertEqual(select_update('0.1.0-alpha.12', [plain]).file_name, 'Engage-Setup-windows.zip')
        # A draft release is not offered.
        self.assertIsNone(select_update('0.1.0-alpha.12', [release('0.1.0-alpha.13', upcoming=True, github=True)]))

    def test_network_response_and_timeout_are_read_only(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps([release('0.1.0-alpha.6')]).encode()
        with patch('engage_setup.updates.urlopen', return_value=response) as request:
            self.assertEqual(check_for_update('0.1.0-alpha.5').version, '0.1.0-alpha.6')
            self.assertEqual(request.call_args.kwargs['timeout'], 8)
        with patch('engage_setup.updates.urlopen', side_effect=TimeoutError('offline')):
            with self.assertRaises(TimeoutError):
                check_for_update('0.1.0-alpha.5')

    def archive(self, extra=None):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            files = {'VERSION': b'0.1.0-alpha.6', 'Engage-Launcher.exe': b'synthetic launcher',
                     'python/python.exe': b'synthetic python', 'python/pythonw.exe': b'synthetic pythonw',
                     'engage_setup/gui.py': b'# synthetic source'}
            for name, data in files.items():
                archive.writestr('package/' + name, data)
            if extra:
                archive.writestr(extra, b'unsafe')
        return stream.getvalue()

    def opener(self, archive, corrupt=False):
        info = select_update('0.1.0-alpha.5', [release('0.1.0-alpha.6')])
        checksum = ('0' * 64 if corrupt else hashlib.sha256(archive).hexdigest()) + '  ' + info.file_name
        def open_response(request, **_):
            data = checksum.encode() if request.full_url.endswith('/SHA256SUMS') else archive
            result = io.BytesIO(data)
            result.headers = {'Content-Length': str(len(data))}
            return result
        return info, open_response

    def test_verified_update_keeps_old_bundle_and_old_shortcut_follows_new_version(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'old'
            root.mkdir()
            (root / 'VERSION').write_text('0.1.0-alpha.5')
            (root / 'keep.txt').write_bytes(b'old files and user data')
            info, opener = self.opener(self.archive())
            with patch('engage_setup.updates.urlopen', side_effect=opener):
                target = prepare_update(info, root, lambda *_: None, threading.Event())
            self.assertFalse((root / 'launcher-update.json').exists())
            activate_update(root, target)
            self.assertEqual(redirect_target(root), target / 'Engage-Launcher.exe')
            self.assertEqual((root / 'keep.txt').read_bytes(), b'old files and user data')
            (target / 'Engage-Launcher.exe').write_bytes(b'tampered')
            self.assertIsNone(redirect_target(root))

    def test_corrupt_or_unsafe_update_never_activates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'old'
            root.mkdir()
            for corrupt, traversal in ((True, None), (False, '../escape')):
                info, opener = self.opener(self.archive(traversal), corrupt)
                with patch('engage_setup.updates.urlopen', side_effect=opener):
                    with self.assertRaises(ValueError):
                        prepare_update(info, root, lambda *_: None, threading.Event())
                self.assertEqual(list(Path(temp).iterdir()), [root])
                self.assertFalse((root / 'launcher-update.json').exists())

    def test_cancel_does_not_create_an_update(self):
        with tempfile.TemporaryDirectory() as temp:
            event = threading.Event()
            event.set()
            info, _ = self.opener(self.archive())
            with self.assertRaises(Cancelled):
                prepare_update(info, Path(temp), lambda *_: None, event)


if __name__ == '__main__':
    unittest.main()
