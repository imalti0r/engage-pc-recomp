"""Extract Engage 2.0.0 and its two DLCs with the pinned nxnative extractor."""
import argparse
import json
import os
import re
import subprocess
import tomllib
from pathlib import Path

from engage_inputs import ROOT, DLC_SPECS, inspect_dlcs, inspect_inputs

TITLE = '0100a6301214e000'
UPDATE = '0100a6301214e800'
TOOL = ROOT / 'toolchain' / 'nx_extract' / 'nx_extract.exe'
OUT = ROOT / 'build' / 'extracted' / 'engage-v200'
LOGS = ROOT / 'build' / 'engage-v200' / 'logs'


def run_tool(keys, arguments, name, title_keys=None):
    environment = dict(os.environ)
    environment.pop('ENGAGE_TITLE_KEYS', None)
    if title_keys is not None and str(title_keys).strip():
        environment['ENGAGE_TITLE_KEYS'] = str(title_keys)
    result = subprocess.run([str(TOOL), str(keys), *map(str, arguments)],
                            capture_output=True, encoding='utf-8', errors='replace',
                            env=environment)
    # External tools must not persist or display possible key-sized values.
    output = re.sub(r'[0-9a-fA-F]{32,}', '<hex removed>', result.stdout + result.stderr)
    LOGS.mkdir(parents=True, exist_ok=True)
    (LOGS / f'{name}.log').write_text(output, encoding='utf-8')
    if result.returncode:
        raise ValueError(f'{name} failed (exit {result.returncode}); see {LOGS / (name + ".log")}')
    return output


def check_content(output, kind, title, version):
    entries = re.findall(r'^content (\w+) ([0-9a-fA-F]{16}) (\d+)\s*$', output, re.M)
    if [(k, t.lower(), int(v)) for k, t, v in entries] != [(kind, title.lower(), version)]:
        field, expected = {
            'Application': ('Base game', 'the Fire Emblem Engage base game NSP/XCI'),
            'Patch': ('Update', 'the Fire Emblem Engage 2.0.0 update NSP'),
            'AddOnContent': ('DLC', f'the Engage DLC package with title ID {title}'),
        }[kind]
        found = ', '.join({'Application': 'a base game', 'Patch': 'an update',
                           'AddOnContent': 'DLC'}.get(k, k) + f' ({t}, version {v})'
                          for k, t, v in entries) or 'no recognized game content'
        raise ValueError(f'{field}: the selected file contains {found}. Select {expected} in the {field} field. '
                         'DLC belongs in the optional DLC fields; a combined package belongs in the combined XCI field.')


def input_path(data, name, optional=False):
    value = data.get(name)
    if optional and (value is None or isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'Missing or invalid input.{name}: set it to a file path in the config or select the file in Setup')
    path = Path(value)
    if not path.is_file():
        raise ValueError(f'Configured input.{name} file is missing or inaccessible; select an existing file')
    return path


def plan_inputs(data, keys, title_keys):
    """The base, update and DLC packages the extraction reads, from the [input] table. A combined
    cartridge dump (base + 2.0.0 update + DLC on one XCI, input.xci) replaces the base and the update
    and carries every DLC the separately named files do not: the extractor reads the base game and
    the update layers from the same package, and each add-on content by its title ID."""
    if not isinstance(data.get('dlc', {}), dict):
        raise ValueError('Invalid input.dlc: use a table of DLC title IDs and file paths')
    dlcs = {title.lower(): Path(path) for title, path in data.get('dlc', {}).items()}
    if not set(dlcs).issubset(DLC_SPECS):
        raise ValueError('The config contains an unsupported DLC title ID')
    xci = input_path(data, 'xci', optional=True)
    base = update = None
    if xci:
        listing = run_tool(keys, ['--contents', xci], 'identity-xci', title_keys)
        found = {}
        for kind, title, version in re.findall(r'^content (\w+) ([0-9a-fA-F]{16}) (\d+)\s*$', listing, re.M):
            found[title.lower()] = (kind, int(version))
        if found.get(TITLE, (None,))[0] != 'Application':
            names = ', '.join({'Application': 'the base game', 'Patch': 'an update',
                               'AddOnContent': 'a DLC', 'Meta': 'a title'}.get(kind, kind) + f' {t}, version {v}'
                              for t, (kind, v) in sorted(found.items())) or 'no recognized game content'
            raise ValueError(f'The combined XCI contains {names}. It must hold the base game ({TITLE}) and '
                             f'the 2.0.0 update ({UPDATE}); a cartridge with only the base game needs the '
                             'update NSP in the update field.')
        if found.get(UPDATE, (None, -1))[0] != 'Patch' or found[UPDATE][1] != 327680:
            versions = ', '.join(f'{t} version {v}' for t, (k, v) in sorted(found.items()) if k == 'Patch') or 'no update'
            raise ValueError(f'The combined XCI holds {versions}; it must hold the 2.0.0 update ({UPDATE}, version 327680). '
                             'A cartridge with an older update needs the 2.0.0 update NSP in the update field.')
        base = update = xci
        from_xci = [t for t in sorted(DLC_SPECS) if t in found and found[t][0] == 'AddOnContent' and t not in dlcs]
        if from_xci:
            print('The combined XCI also carries DLC ' + ', '.join(t.upper() for t in from_xci), flush=True)
        dlcs.update({t: xci for t in from_xci})
    else:
        base, update = (input_path(data, name) for name in ('base', 'update'))
    for path in (TOOL, keys, base, update, *dlcs.values()):
        if not path.is_file():
            raise ValueError(f'Missing input or extractor: {path}')
    if title_keys is not None and not title_keys.is_file():
        raise ValueError('Configured title_keys file is missing')
    if xci:
        # the combined listing above already named the base game and the update it holds
        print('Verified the combined XCI: base game and 2.0.0 update', flush=True)
    else:
        for label, path, kind, title, version in (
            ('base', base, 'Application', TITLE, 0),
            ('update', update, 'Patch', UPDATE, 327680),
        ):
            check_content(run_tool(keys, ['--contents', path], f'identity-{label}', title_keys), kind, title, version)
            print(f'Verified {label} package identity', flush=True)
    for title, path in dlcs.items():
        if path == xci:
            continue
        check_content(run_tool(keys, ['--contents', path], f'identity-dlc-{title}', title_keys),
                      'AddOnContent', title, 0)
        print(f'Verified DLC {title.upper()} package identity', flush=True)
    return base, update, dlcs


def main():
    global TOOL, OUT, LOGS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config.local.toml')
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--tool', type=Path, default=TOOL)
    parser.add_argument('--logs', type=Path, default=LOGS)
    args = parser.parse_args()
    TOOL, OUT, LOGS = args.tool, args.out, args.logs
    try:
        data = tomllib.loads(args.config.read_text(encoding='utf-8')).get('input')
        if not isinstance(data, dict):
            raise ValueError('Invalid input table: add [input] with keys, base and update file paths')
        keys = input_path(data, 'keys')
        title_keys = input_path(data, 'title_keys', optional=True)
        base, update, dlcs = plan_inputs(data, keys, title_keys)
        if (OUT / 'ExeFS').exists() or (OUT / 'RomFS').exists():
            raise ValueError('ExeFS/RomFS already exist: inspect the previous extraction before retrying')
        OUT.mkdir(parents=True, exist_ok=True)
        print('Extracting base + update with integrity checks; this can take several minutes', flush=True)
        output = run_tool(keys, [base, update, OUT, '--app', TITLE], 'base-update', title_keys)
        if not re.search(r'^display version 2\.0\.0\s*$', output, re.M):
            raise ValueError('Extracted control data did not report version 2.0.0')
        report = inspect_inputs(OUT / 'ExeFS', OUT / 'RomFS')
        for title, path in dlcs.items():
            index, _ = DLC_SPECS[title]
            destination = OUT / 'aoc' / str(index)
            run_tool(keys, ['--aoc', path, destination, title], f'dlc-{index}', title_keys)
        report['dlc'] = inspect_dlcs(OUT / 'aoc', require_all=False)
        (OUT / 'inputs.json').write_text(
            json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(f'Verified Engage 2.0.0 and extracted {len(dlcs)} DLC packages.')
    except (OSError, ValueError, KeyError, TypeError) as error:
        message = re.sub(r'[0-9a-fA-F]{32,}', '<hex removed>', str(error)).replace('\n', ' ')
        parser.exit(1, f'ENGAGE_SETUP_ERROR: {message}\n')


if __name__ == '__main__':
    main()
