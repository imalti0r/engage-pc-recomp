# Documentation screenshots

| File | What it shows |
| --- | --- |
| `launcher.png` | The launcher's Play page with an installation selected: the display summary, the mods count and the save buttons. |
| `settings.png` | The launcher's settings page: window mode, window size, presentation, DLSS mode, render scale, button prompts and the rest. |
| `setup.png` | The empty setup form. |

The launcher pictures are rendered by `build/launcher_shots.py`, which builds the real launcher window off-screen and
saves its own pixels with `PrintWindow`. That keeps them free of the desktop, of other windows, and of this machine's
paths. Regenerate them with:

    .venv-py314\Scripts\python build\launcher_shots.py zh-Hans "<install folder>" play,settings

`settings.png` is cropped above the game-folder line, because that line shows a path from the machine that made it.

None of them contains game content, key values, gameplay or extracted assets. The launcher background and lettering
are the project's own generated artwork, with provenance in [the artwork notes](../../engage_setup/art/README.md).
The source-release audit allows these pictures by exact path and SHA-256
(`REVIEWED_SCREENSHOTS` in `tools/make_engage_source_release.py`); changed or additional screenshots are refused
until they are reviewed and listed there.
