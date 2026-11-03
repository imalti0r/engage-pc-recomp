# Making a release

## What goes in a release

Ship the public runtime, setup tools and source. Setup extracts and compiles the player's own files into `engage_game.dll` on their PC. Shared fonts are taken from their inputs; the public runtime uses an original icon.

Never upload a local install folder, `engage_game.dll`, an older monolithic `engage.exe`, game dumps, keys, firmware, saves, generated game code, extracted artwork or shader caches. The `bin/engage.exe` built without game inputs by the release builder is the public runtime and may ship with its `engage.json` contract/hash file. Keep the upstream licenses and credits with the tools.

For source archives:

1. Run the content guard on the working tree and staged files.
2. Run the Engage tests and continuation test.
3. Use `tools/make_engage_source_release.py` to audit and package the exact commit being released.
4. Check the archive and checksums before uploading. Keep the tag on that commit.

GitHub's source checks run without game files or keys. They help catch mistakes, but they don't replace playing the game. Local gameplay folders don't belong in Actions artifacts.

## Building Windows setup

Engage uses `engage_setup`. The inherited `python -m installer` command is still for TotK.

`tools/make_engage_release.py` bundles Python, the compiler, runtime source and the self-contained extractor. It also includes the licensed Roboto font used by the settings menu. Keep that font and its license in the package; leaving it out caused the alpha.2 F1 crash.

From a clean, committed checkout, run this with Python 3.14:

```powershell
.venv-py314\Scripts\python.exe tools\make_engage_release.py `
  --out build\release\Engage-Setup-<version>-windows `
  --zip build\release\Engage-Setup-<version>-windows.zip
```

The builder checks the bundled Python, the missing-input error path and the setup window. It scans the package for game content, writes an inventory and makes a checksum file. Check the finished ZIP against that inventory too.

For a public release, merge the reviewed changes from `dev` into `main`, tag that source, and build from it. Upload the checked ZIPs to the project's generic package registry, then create the release with `glab release create <tag> --notes-file <file>` and attach each ZIP as a release link whose file path is its file name, so the README's `/-/releases/<tag>/downloads/<name>` links resolve. GitLab has no draft releases: set the release date in the future (`--released-at`) to keep it hidden as an upcoming release, check the hashes, then move the date to now to publish.

## What to test

Try a fresh installation with the bundled tools and no developer tools on PATH. Check cancellation/retry, saves and settings, first launch, audio and the F1 menu. Setup runs `--probe-menu-font` before installing the compiled game, but the menu should also be opened and checked in a real run.

Keep early builds marked as prereleases. Before calling the port broadly supported, test on a clean Windows machine and more hardware. Record what worked, what failed and what hasn't been checked yet.

## Results so far

Local testing has been on Windows 11 with an RTX 4060:

- A fresh install on a second drive completed with both DLCs and all six shared fonts.
- Extraction and packing covered 206,874 files and a 16,572,416,159-byte RomFS image.
- Continuation-enabled code generation reported no unsupported instructions.
- Setup resumed after a packaging-path fix, then finished compiling, installing and cleaning up.
- The installed CPU/audio checks and Engage filesystem/DLC probe passed.
- The opening movie rendered in a timed boot test, audio opened, and the game exited normally. First-launch shader work caused pauses.
- The alpha.3 menu fix passed the font check and rendered all six settings tabs using a separate test profile. Screen and Sound were checked for readable text.
- The setup window, missing-input check and package content scan passed. The README screenshot shows the empty setup form, with no personal paths or game artwork.

Clean-machine installs, save/load, DLC gameplay, progress after the first battle and full-game stability still need testing. Keep the local test logs and gameplay screenshots out of release assets.

## Color reports

The dark and blue unit-information panels were shown in different Emblem states. A [gameplay reference](https://images.igdb.com/igdb/image/upload/t_1080p_2x/sciwxx.webp) also shows a dark panel for Alear without an Emblem partner. That alone doesn't confirm a rendering bug. Compare the same unit, state and settings before changing gamma, blending or shaders. No renderer change was made for this report.
