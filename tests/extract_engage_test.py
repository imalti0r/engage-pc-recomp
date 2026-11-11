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

    def test_combined_xci_identity_and_errors(self):
        listing = ('content Application 0100a6301214e000 0\n'
                   'content Patch 0100a6301214e800 327680\n'
                   'content AddOnContent 0100a6301214f001 0\n'
                   'content AddOnContent 0100a6301214f002 0\n')
        with tempfile.TemporaryDirectory() as temporary:
            keys = Path(temporary) / 'prod.keys'
            keys.write_text('# synthetic test file\n')
            xci = Path(temporary) / 'combined.xci'
            xci.write_text('# synthetic test file\n')
            result = subprocess.CompletedProcess([], 0, listing, '')
            tool = Path(temporary) / 'nx_extract.exe'
            tool.write_text('# synthetic test file\n')
            with tempfile.TemporaryDirectory() as out, patch.object(extract_engage, 'LOGS', Path(out)), \
                    patch.object(extract_engage, 'TOOL', tool), \
                    patch.object(extract_engage.subprocess, 'run', return_value=result) as run, \
                    patch('builtins.print'):
                base, update, dlcs = extract_engage.plan_inputs({'keys': str(keys), 'xci': str(xci)}, keys, None)
            # the combined XCI needs one contents listing; no per-file identity runs for the
            # base game, the update or the DLCs it carries (the add-on content calls belong
            # to the extraction, not the planning)
            self.assertEqual([c.args[0] for c in run.call_args_list], [[str(tool), str(keys), '--contents', str(xci)]])
            # a separately named DLC file wins over the XCI's copy
            dlc1 = Path(temporary) / 'dlc1.nsp'
            dlc1.write_text('# synthetic test file\n')
            dlc_listing = 'content AddOnContent 0100a6301214f001 0\n'
            # run_tool's child command is [<tool>, <keys>, --contents, <package>]: the listing
            # depends on the package, the XCI gets the combined one, the DLC file its own
            by_package = lambda arguments, **_: subprocess.CompletedProcess(
                [], 0, listing if arguments[3].endswith('.xci') else dlc_listing, '')
            with tempfile.TemporaryDirectory() as out, patch.object(extract_engage, 'LOGS', Path(out)), \
                    patch.object(extract_engage, 'TOOL', tool), \
                    patch.object(extract_engage.subprocess, 'run', side_effect=by_package) as run, \
                    patch('builtins.print'):
                _, _, dlcs = extract_engage.plan_inputs(
                    {'keys': str(keys), 'xci': str(xci),
                     'dlc': {'0100a6301214f001': str(dlc1)}}, keys, None)
            self.assertEqual(dlcs['0100a6301214f001'], dlc1)
            self.assertEqual(dlcs['0100a6301214f002'], xci)
            calls = [c.args[0] for c in run.call_args_list]
            self.assertIn([str(tool), str(keys), '--contents', str(dlc1)], calls)
        for broken, why in (
            (listing.replace('Patch 0100a6301214e800 327680', 'Patch 0100a6301214e800 0'), '2.0.0'),
            (listing.replace('Patch 0100a6301214e800 327680\n', ''), '2.0.0'),
            (listing.replace('Application 0100a6301214e000 0', 'Application 0100a6301214e001 0'), '0100a6301214e000'),
        ):
            with tempfile.TemporaryDirectory() as temporary:
                keys = Path(temporary) / 'prod.keys'
                keys.write_text('# synthetic test file\n')
                xci = Path(temporary) / 'combined.xci'
                xci.write_text('# synthetic test file\n')
                result = subprocess.CompletedProcess([], 0, broken, '')
                with tempfile.TemporaryDirectory() as out, patch.object(extract_engage, 'LOGS', Path(out)), \
                        patch.object(extract_engage, 'TOOL', keys), \
                        patch.object(extract_engage.subprocess, 'run', return_value=result), \
                        patch('builtins.print'), self.assertRaises(ValueError) as raised:
                    extract_engage.plan_inputs({'keys': str(keys), 'xci': str(xci)}, keys, None)
                self.assertIn(why, str(raised.exception))

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
