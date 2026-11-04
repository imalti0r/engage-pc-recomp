"""Real LibHac regression tests; restore the extractor project before running."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / 'build/nx-extract-artifacts'


class NxExtractKeysTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(['dotnet', 'build', str(ROOT / 'tools/nx_extract/nx_extract.csproj'),
                        '-c', 'Release', '--artifacts-path', str(ARTIFACTS), '--no-restore'], check=True)
        cls.dll = ARTIFACTS / 'bin/nx_extract/release/nx_extract.dll'

    def test_key_paths_in_all_modes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            keys = root / 'synthetic keys.keys'
            keys.write_text('# No game keys used\n')
            package = root / 'empty.nsp'
            package.write_bytes(b'PFS0' + bytes(0x200 - 4))
            modes = (['--title', str(package)], ['--contents', str(package)],
                     [str(package), '-', str(root / 'out')],
                     ['--aoc', str(package), str(root / 'dlc')])
            cases = (('', None, 'input.keys'), ('   ', None, 'input.keys'),
                     (str(root / 'missing'), None, 'input.keys'),
                     (str(root), None, 'input.keys'),
                     (str(keys), str(root / 'missing'), 'input.title_keys'))
            for mode in modes:
                for common, title, message in cases:
                    with self.subTest(mode=mode[0], common=common, title=title):
                        result = self.run_tool(common, mode, title)
                        self.assertEqual(result.returncode, 2, result.stderr)
                        self.assertIn(message, result.stderr)
                        self.assertNotIn('Unhandled exception', result.stderr)
            # Empty PFS0 reaches package inspection (exit 5), proving key loading succeeded.
            for mode in modes[:2]:
                for title in (None, '', '   ', str(keys)):
                    with self.subTest(mode=mode[0], title=title):
                        result = self.run_tool(str(keys), mode, title)
                        self.assertEqual(result.returncode, 5, result.stderr)
                        self.assertIn('no ', result.stdout)
                        self.assertEqual(result.stderr, '')

    def run_tool(self, keys, mode, title):
        environment = dict(os.environ)
        environment.pop('ENGAGE_TITLE_KEYS', None)
        if title is not None:
            environment['ENGAGE_TITLE_KEYS'] = title
        return subprocess.run(['dotnet', str(self.dll), keys, *mode], env=environment,
                              capture_output=True, text=True)


if __name__ == '__main__':
    unittest.main()
