import subprocess
import os
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import extract_engage


class ExtractEngageTest(unittest.TestCase):
    def test_config_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            valid = Path(temporary) / 'keys with spaces.keys'
            valid.write_text('# synthetic test file\n')
            self.assertEqual(extract_engage.input_path({'keys': str(valid)}, 'keys'), valid)
            for value in (None, '', '   ', 42, [], str(valid / 'missing')):
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'input.keys'):
                    extract_engage.input_path({'keys': value}, 'keys')
            for value in (None, '', '   '):
                self.assertIsNone(extract_engage.input_path({'title_keys': value}, 'title_keys', optional=True))
            with self.assertRaisesRegex(ValueError, 'input.title_keys'):
                extract_engage.input_path({'title_keys': str(valid / 'missing')}, 'title_keys', optional=True)

    def test_invalid_config_exits_without_traceback(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / 'inputs.toml'
            for content in ('', '[input]\nkeys = 42', 'input = "wrong"', '[input', '[input]\nkeys = ""'):
                config.write_text(content)
                with patch.object(sys, 'argv', ['extract_engage', '--config', str(config)]), patch('sys.stderr', new_callable=io.StringIO) as error:
                    with self.assertRaises(SystemExit) as exit:
                        extract_engage.main()
                    self.assertEqual(exit.exception.code, 1)
                    self.assertIn('ENGAGE_SETUP_ERROR: ', error.getvalue())
                    self.assertNotIn('Traceback', error.getvalue())

    def test_optional_title_keys_environment(self):
        result = subprocess.CompletedProcess([], 0, '', '')
        with tempfile.TemporaryDirectory() as temporary, patch.object(extract_engage, 'LOGS', Path(temporary)), patch.dict(os.environ, ENGAGE_TITLE_KEYS='inherited.keys'):
            for value in (None, '', '   ', Path('selected.keys')):
                with patch.object(extract_engage.subprocess, 'run', return_value=result) as run:
                    extract_engage.run_tool('prod.keys', [], 'env', value)
                    environment = run.call_args.kwargs['env']
                    if value == Path('selected.keys'):
                        self.assertEqual(environment['ENGAGE_TITLE_KEYS'], 'selected.keys')
                    else:
                        self.assertNotIn('ENGAGE_TITLE_KEYS', environment)

    def test_package_identity(self):
        valid = 'content Patch 0100a6301214e800 327680\n'
        extract_engage.check_content(valid, 'Patch', extract_engage.UPDATE, 327680)
        for output in ('', valid * 2, valid.replace('327680', '0'),
                       valid.replace('1214e800', '1214e000')):
            with self.subTest(output=output), self.assertRaises(ValueError):
                extract_engage.check_content(output, 'Patch', extract_engage.UPDATE, 327680)

    def test_dlc_in_base_field_explains_correction(self):
        with self.assertRaisesRegex(ValueError, 'Base game:.*contains DLC.*Select.*base game NSP/XCI'):
            extract_engage.check_content('content AddOnContent 0100a6301214f001 0\n',
                                         'Application', extract_engage.TITLE, 0)

    def test_tool_logs_redact_key_sized_values_and_fail_closed(self):
        secret = 'ab' * 16
        with tempfile.TemporaryDirectory() as temporary:
            logs = Path(temporary)
            for code in (0, 1):
                result = subprocess.CompletedProcess([], code, f'key = {secret}\n', '')
                with patch.object(extract_engage, 'LOGS', logs), patch.object(
                    extract_engage.subprocess, 'run', return_value=result
                ):
                    if code:
                        with self.assertRaises(ValueError):
                            extract_engage.run_tool(Path('prod.keys'), [], 'test')
                    else:
                        self.assertNotIn(secret, extract_engage.run_tool(Path('prod.keys'), [], 'test'))
                self.assertNotIn(secret, (logs / 'test.log').read_text())


if __name__ == '__main__':
    unittest.main()
