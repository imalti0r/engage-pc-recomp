"""Exercise the C mod manager on synthetic folders, without any game content."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TITLE = '0100A6301214E000'


class ModsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pinned = ROOT / 'toolchain/engage/llvm/bin'
        cc = str(pinned / 'clang.exe') if os.name == 'nt' else shutil.which('clang')
        cxx = str(pinned / 'clang++.exe') if os.name == 'nt' else shutil.which('clang++')
        if not cc or not Path(cc).is_file() or not cxx or not Path(cxx).is_file():
            raise unittest.SkipTest('Clang is not installed')
        cls.temp = tempfile.TemporaryDirectory()
        work = Path(cls.temp.name)
        cls.binary = work / 'mods.exe'
        for command in ([cc, '-std=gnu11', '-I', str(ROOT / 'runtime'), '-c', str(ROOT / 'runtime/mods.c'), '-o', str(work / 'mods.o')],
                        [cxx, '-std=c++17', '-static', '-I', str(ROOT / 'runtime'), str(ROOT / 'tests/mods_harness.cpp'), str(work / 'mods.o'), '-o', str(cls.binary)]):
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(result.stdout + result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_mods(self, root, disabled='', toggle=None):
        args = [str(self.binary), str(root), disabled]
        if toggle is not None:
            args.append(str(toggle))
        output = subprocess.check_output(args, encoding='utf-8')
        return [line.split('\t') for line in output.splitlines()]

    def put(self, root, relative):
        path = root / 'mods' / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('synthetic')

    def test_layouts_conflicts_and_code_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, prefix in [('a', 'romfs'), ('B', f'{TITLE}/romfs'),
                                 ('c', f'contents/{TITLE}/romfs'), ('d', f'atmosphere/contents/{TITLE}/romfs')]:
                self.put(root, f'{name}/{prefix}/shared.txt')
                self.put(root, f'{name}/{prefix}/{name}.txt')
            self.put(root, 'e/exefs/code.ips')
            self.put(root, 'f/romfs/f.txt')
            self.put(root, 'f/exefs/code.ips')
            rows = self.run_mods(root)
            self.assertEqual(sum(r == ['file', 'shared.txt'] for r in rows), 1)
            mods = {r[1]: r for r in rows if r[0] == 'mod'}
            self.assertEqual(mods['a'][2:9], ['1', '1', '1', '0', '2', '2', '0'])
            self.assertEqual(mods['B'][8], '1')
            self.assertEqual(mods['e'][2], '0')
            self.assertIn('Code-only', mods['e'][9])
            self.assertEqual(mods['f'][5], '1')

    def test_toggle_persists_without_changing_active_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            name = 'Mod, café'
            self.put(root, f'{name}/romfs/x')
            rows = self.run_mods(root, toggle=0)
            self.assertIn(['setting', name.encode().hex()], rows)
            self.assertIn(['restart', '1'], rows)
            row = next(r for r in rows if r[0] == 'mod')
            self.assertEqual(row[3:5], ['1', '0'])
            restarted = self.run_mods(root, name.encode().hex())
            self.assertFalse(any(r[0] == 'file' for r in restarted))
            self.assertIn(['restart', '0'], restarted)

    def test_link_rejects_entire_mod_and_empty_folder_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.run_mods(root)
            self.assertTrue((root / 'mods').is_dir())
            self.put(root, 'linked/romfs/valid')
            try:
                (root / 'mods/linked/romfs/escape').symlink_to(root, target_is_directory=True)
            except OSError:
                self.skipTest('symlink creation is unavailable')
            rows = self.run_mods(root)
            self.assertFalse(any(r[0] == 'file' for r in rows))
            self.assertEqual(next(r for r in rows if r[0] == 'mod')[2], '0')


if __name__ == '__main__':
    unittest.main()
