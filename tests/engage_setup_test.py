"""Installer safety and recovery tests, using synthetic files only."""
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engage_setup.model import Form, TITLE, installed_state
from engage_setup.pipeline import Pipeline, redact, remove_work, validate_destination, write_json
from installer.events import Reporter
from installer.guilogic import STEP_ORDER


class SetupTest(unittest.TestCase):
    def test_extraction_failure_reason_reaches_setup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pipeline = Pipeline(Form(dest=temp), SimpleNamespace(root=root), Reporter(out=io.StringIO()))
            pipeline.work.mkdir()
            pipeline.step = 'extract'
            reason = 'Base game: the selected file contains DLC. Select the Engage base game NSP/XCI.'
            child = SimpleNamespace(stdout=iter(['progress\n', f'ENGAGE_SETUP_ERROR: {reason}\n']),
                                    wait=lambda **kwargs: 1, poll=lambda: 1)
            with patch('engage_setup.pipeline.subprocess.Popen', return_value=child):
                with self.assertRaises(ValueError) as error:
                    pipeline.command(['synthetic-extractor'])
            self.assertEqual(str(error.exception), reason)

    def test_form_requires_firmware_and_accepts_optional_dlcs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            file = root / 'own-input'
            file.touch()
            form = Form(base=str(file), update=str(file), keys=str(file), firmware=str(root),
                        dest=str(root / 'install'), lang='en-US')
            self.assertEqual(form.problems(), [])
            command = form.command('python.exe')
            self.assertEqual(command[:5], ['python.exe', '-X', 'utf8', '-m', 'engage_setup'])
            self.assertNotIn('--dlc1', command)
            form.dlc1 = str(root / 'missing')
            self.assertIn('ui.missing_dlc1', form.problems())
            form.firmware = ''
            self.assertIn('ui.need_firmware', form.problems())

    def test_form_takes_a_combined_xci_instead_of_base_and_update(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            keys = root / 'prod.keys'
            keys.touch()
            xci = root / 'combined.xci'
            xci.touch()
            form = Form(xci=str(xci), keys=str(keys), firmware=str(root), dest=str(root / 'install'), lang='en-US')
            self.assertEqual(form.problems(), [])
            self.assertIn('--xci', form.command('python.exe'))
            form.xci = ''
            self.assertEqual(form.problems(), ['ui.need_base', 'ui.need_update'])

    def test_extract_writes_the_combined_xci_into_the_config(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = SimpleNamespace(root=root, extractor=root / 'nx_extract.exe')
            pipeline = Pipeline(Form(xci='C:/dumps/combined.xci', keys='C:/dumps/prod.keys',
                                     firmware=str(root), dest=str(root / 'install')), paths,
                                Reporter(out=io.StringIO()))
            pipeline.work.mkdir(parents=True)
            seen = []

            def capture(script, *arguments):
                if '--config' not in arguments:
                    return
                config = Path(arguments[arguments.index('--config') + 1])
                seen.append((Path(script).name, config.read_text(encoding='utf-8')))

            with patch.object(pipeline, 'python', side_effect=capture), patch.object(pipeline, 'reporter'):
                pipeline.extract()
            extract = next(text for name, text in seen if name == 'extract_engage.py')
            self.assertIn('xci = "C:/dumps/combined.xci"', extract)
            self.assertNotIn('base =', extract)
            self.assertNotIn('update =', extract)

    def test_finished_install_needs_no_input_files(self):
        with tempfile.TemporaryDirectory() as temp:
            form = Form(dest=temp, lang='en-US')
            self.assertIn('ui.need_base', form.problems())
            write_json(Path(temp) / 'engage-install.json', {'format': 1, 'title_id': TITLE, 'done': ['extract']})
            self.assertIn('ui.need_base', form.problems())
            write_json(Path(temp) / 'engage-install.json', {'format': 1, 'title_id': TITLE, 'done': list(STEP_ORDER[1:])})
            self.assertEqual(form.problems(), [])

    def test_reject_foreign_folder_and_input_overlap(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            setup = root / 'setup'
            setup.mkdir()
            dest = root / 'install'
            dest.mkdir()
            (dest / 'important.txt').write_text('keep')
            with self.assertRaisesRegex(ValueError, 'not empty'):
                validate_destination(dest, [], setup)
            with self.assertRaisesRegex(ValueError, 'separate'):
                validate_destination(dest, [dest / 'game.nsp'], setup)
            with self.assertRaisesRegex(ValueError, 'outside'):
                validate_destination(setup / 'install', [], setup)
            with self.assertRaisesRegex(ValueError, 'outside'):
                validate_destination(setup / 'install', [], setup / '..' / 'setup')
            self.assertEqual((dest / 'important.txt').read_text(), 'keep')

    def test_state_identity_and_safe_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_json(root / 'engage-install.json', {'format': 1, 'title_id': 'other'})
            self.assertIsNone(installed_state(root))
            write_json(root / 'engage-install.json', {'format': 1, 'title_id': TITLE})
            self.assertIsNotNone(installed_state(root))
            work = root / '.setup-work'
            work.mkdir()
            profile = root / 'profile'
            profile.mkdir()
            with self.assertRaisesRegex(ValueError, 'outside'):
                remove_work(profile, work)
            self.assertTrue(profile.is_dir())
            generated = work / 'generated'
            generated.mkdir()
            remove_work(generated, work)
            self.assertFalse(generated.exists())

    def test_failed_step_is_not_checkpointed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pipeline = Pipeline(Form(dest=str(root / 'game')), SimpleNamespace(release='test'), Reporter(out=io.StringIO()))
            pipeline.check = lambda: None
            pipeline.fingerprint = lambda: 'synthetic'
            pipeline.extract = lambda: (_ for _ in ()).throw(ValueError('synthetic failure'))
            with self.assertRaisesRegex(ValueError, 'synthetic failure'):
                pipeline.run()
            state = installed_state(pipeline.dest)
            self.assertEqual(state['done'], [])
            self.assertEqual(pipeline.step, 'extract')

    def test_no_raw_hex_in_tool_log(self):
        secret = 'ab' * 32
        self.assertNotIn(secret, redact('tool failed with ' + secret))
        self.assertEqual(redact('ordinary error'), 'ordinary error')

    def test_prepare_retry_keeps_existing_settings_and_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pipeline = Pipeline(Form(dest=str(root), lang='en-US'), SimpleNamespace(), Reporter(out=io.StringIO()))
            pipeline.state = {'format': 1, 'title_id': TITLE, 'done': []}
            pipeline.command = lambda *args, **kwargs: None
            pipeline.dest.mkdir(exist_ok=True)
            pipeline.build.mkdir(parents=True)
            for name in ('engage.exe', 'engage_game.dll', 'romfs-index.bin', 'SDL3.dll', 'totk_xlate.exe', 'totk_xlate.id'):
                (pipeline.build / name).write_bytes(b'synthetic host output')
            for directory in (pipeline.extracted / 'ExeFS', pipeline.extracted / 'packed-romfs', pipeline.work / 'fonts'):
                directory.mkdir(parents=True)
                (directory / 'synthetic').touch()
            settings = root / 'engage.ini'
            settings.write_text('volume = 37\n')
            (root / 'profile').mkdir()
            save = root / 'profile/keep-save'
            save.write_bytes(b'keep')
            mod = root / 'mods/keep-mod/romfs/file'
            mod.parent.mkdir(parents=True)
            mod.write_bytes(b'keep mod')
            pipeline.prepare()
            pipeline.prepare()
            self.assertEqual(settings.read_text(), 'volume = 37\n')
            self.assertEqual(save.read_bytes(), b'keep')
            self.assertEqual(mod.read_bytes(), b'keep mod')
            self.assertTrue((root / 'engage.exe').exists())
            self.assertTrue((root / 'romfs-index.bin').exists())
            self.assertTrue((root / 'engage_game.dll').exists())
            launcher = (root / 'Play Engage.cmd').read_text()
            self.assertNotIn('TOTK_', launcher)
            self.assertIn('%*', launcher)

    def test_failed_pair_replacement_restores_previous_executable_and_dll(self):
        with tempfile.TemporaryDirectory() as temp:
            pipeline = Pipeline(Form(dest=temp), SimpleNamespace(), Reporter(out=io.StringIO()))
            pipeline.build.mkdir(parents=True)
            for name in ('engage.exe', 'engage_game.dll'):
                (pipeline.dest / name).write_bytes(b'old ' + name.encode())
                (pipeline.build / name).write_bytes(b'new ' + name.encode())
            import os
            replace = os.replace

            def locked_executable(source, target):
                if Path(source).name == 'engage.exe.new':
                    raise PermissionError('synthetic running executable')
                return replace(source, target)

            with patch('engage_setup.pipeline.os.replace', side_effect=locked_executable):
                with self.assertRaisesRegex(ValueError, 'Close Engage'):
                    pipeline.deploy_game()
            for name in ('engage.exe', 'engage_game.dll'):
                self.assertEqual((pipeline.dest / name).read_bytes(), b'old ' + name.encode())
                self.assertFalse((pipeline.dest / (name + '.new')).exists())

    def test_legacy_install_migrates_even_when_release_string_matches(self):
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / 'game'
            (dest / 'exefs').mkdir(parents=True)
            (dest / 'exefs/main').touch()
            write_json(dest / 'engage-install.json', {'format': 1, 'title_id': TITLE, 'release': 'same',
                       'done': list(STEP_ORDER[1:]), 'assets': ['romfs', 'exefs']})
            pipeline = Pipeline(Form(dest=str(dest)), SimpleNamespace(release='same', root=Path(temp)),
                                Reporter(out=io.StringIO()))
            (Path(temp) / 'recomp').mkdir()
            (Path(temp) / 'recomp/patches-engage-v200.txt').touch()
            pipeline.check = lambda: None
            pipeline.fingerprint = lambda: 'existing inputs'
            pipeline.validate_resume = lambda: None
            ran = []
            for step in STEP_ORDER[1:]:
                setattr(pipeline, step, lambda step=step: ran.append(step))
            pipeline.run()
            self.assertEqual(ran, ['lift', 'compile', 'prepare', 'cleanup'])

    def test_new_release_reruns_only_lift_compile_and_prepare(self):
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / 'game'
            (dest / 'exefs').mkdir(parents=True)
            (dest / 'exefs/main').touch()
            write_json(dest / 'engage-install.json', {'format': 1, 'title_id': TITLE, 'release': 'old',
                'inputs': 'moved-files', 'done': list(STEP_ORDER[1:]), 'assets': ['romfs', 'exefs']})
            pipeline = Pipeline(Form(dest=str(dest)), SimpleNamespace(release='new', root=Path(temp)), Reporter(out=io.StringIO()))
            (Path(temp) / 'recomp').mkdir()
            (Path(temp) / 'recomp/patches-engage-v200.txt').touch()
            pipeline.check = lambda: None
            pipeline.fingerprint = lambda: 'other-files'
            pipeline.validate_resume = lambda: None
            ran = []
            for step in STEP_ORDER[1:]:
                setattr(pipeline, step, lambda step=step: ran.append(step))
            pipeline.run()
            self.assertEqual(ran, ['lift', 'compile', 'prepare', 'cleanup'])
            ran.clear()
            pipeline.paths = SimpleNamespace(release='newer', root=Path(temp))
            (pipeline.generated).mkdir(parents=True)
            (pipeline.generated / 'layout.json').touch()
            pipeline.state['lift_key'] = pipeline.lift_key()
            write_json(dest / 'engage-install.json', pipeline.state)
            pipeline.run()
            self.assertEqual(ran, ['compile', 'prepare', 'cleanup'])
            self.assertEqual(installed_state(dest)['release'], 'newer')
            self.assertTrue((pipeline.extracted / 'ExeFS/main').exists())

    def test_cancelled_step_is_not_checkpointed(self):
        with tempfile.TemporaryDirectory() as temp:
            pipeline = Pipeline(Form(dest=str(Path(temp) / 'game')), SimpleNamespace(release='test'), Reporter(out=io.StringIO()))
            pipeline.check = lambda: None
            pipeline.fingerprint = lambda: 'synthetic'
            pipeline.extract = lambda: (_ for _ in ()).throw(KeyboardInterrupt())
            with self.assertRaises(KeyboardInterrupt):
                pipeline.run()
            self.assertEqual(installed_state(pipeline.dest)['done'], [])


if __name__ == '__main__':
    unittest.main()
