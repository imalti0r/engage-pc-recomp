# Engage PC Recomp

A native Windows port of **Fire Emblem Engage 2.0.0**, built on [TotK Recomp](https://github.com/valentderah/totk-pc-recomp).

[![Source checks](https://gitlab.com/engage-pc-recomp/engage-pc-recomp/badges/main/pipeline.svg)](https://gitlab.com/engage-pc-recomp/engage-pc-recomp/-/pipelines)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

[Download Windows Setup](https://gitlab.com/engage-pc-recomp/engage-pc-recomp/-/releases/engage-v0.1.0-alpha.5/downloads/Engage-Setup-0.1.0-alpha.5-windows.zip) · [Setup guide](docs/installing-engage.md) · [Report a bug](https://gitlab.com/engage-pc-recomp/engage-pc-recomp/-/issues/new) · [Build from source](docs/building-engage.md)

**This is still an early alpha.** The first battle, attack cutscenes and audio work, but the full game hasn't been tested. Expect bugs, and back up your saves.

## Installing

The launcher handles installation, Play, settings, RomFS mods, save backups and updates. Python, the compiler and the extractor are included.

**The screenshots and launcher instructions below describe `dev`.** The linked alpha.5 download uses the older `Engage-Setup.exe` and does not include these launcher features. Merging into `dev` does not publish a new installer; use a launcher-enabled test build until the next release.

![Engage launcher with Play, Mods, Saves and Settings](docs/screenshots/launcher.png)

For a launcher-enabled build:

1. Extract the entire setup ZIP, keeping its files and folders together.
2. Open **Engage-Launcher.exe** and choose **Setup / Update**. Select your base game, **2.0.0** update, keys and extracted firmware folder. Both DLCs are optional.
3. Pick an empty install folder with **40 GiB free** and click **Install Engage**.
4. Setup copies the launcher and tools into your game folder, verifies them, and switches to the installed launcher. You can then delete the original extracted setup folder. Use the game folder's **Engage-Launcher.exe** from now on; keep its **.launcher** folder with the game.

![Engage Setup with required inputs and optional DLC and title keys](docs/screenshots/setup.png)

If you're not sure which files to pick, the [setup guide](docs/installing-engage.md) walks through each field and the common errors.

**F1** opens in-game settings. The [setup guide](docs/installing-engage.md) explains each input, installation folders, recovery and older alpha.5 installs.

## RomFS mods

Open **Mods** to import a ZIP or extracted mod folder, search your collection, inspect file overlaps, and enable or disable mods. You can also use **F1 → Mods** in-game. Changes take effect after restarting the game; loaded assets cannot be switched live. The original game data is left unchanged.

Use mods made for Engage 2.0.0 that replace or add RomFS files. Code patches and Cobalt plugins are not supported. See [supported folder layouts, priority and limitations](docs/launcher.md#romfs-mods).

## Updates

The installed launcher checks for newer published releases when it opens. **Settings → Check for updates** checks manually. An available update shows **Update now** and **Later**; updates are not installed without your confirmation.

The updater verifies the download, restarts the launcher and runs Setup / Update for your selected game folder. Saves, settings and mods are kept. Valid extraction and build caches are reused, although a compatibility change can require rebuilding the private game DLL. Keep `.launcher` and `.setup-work` with your installation. [Update and recovery details](docs/installing-engage.md#updating).

**Use alpha.3 or newer.** Alpha.2 was missing the menu font, which could crash the game when you pressed F1. That's fixed in [#2](https://gitlab.com/engage-pc-recomp/engage-pc-recomp/-/merge_requests/2).

## What's working

- Opening movie, title screen and character preview.
- The first battle, including attack cutscenes.
- Audio, keyboard and gamepad input.
- The F1 settings menu. All six tabs were checked in the repaired build.
- Development launcher: installed-copy handoff, settings, RomFS mod controls, save backups and verified update handling. Full installations and updates on a clean Windows machine still need testing.
- Game output resolution and 3D render scale controls, plus corrected exploration movement speed at 60 FPS.
- Loading an existing Chapter 1 exploration save in an isolated test profile.
- Both DLC packages are detected and mounted. Their actual content still needs testing.

Writing a new save and reloading it, later progression and longer play sessions still need checking. There are also graphics issues to investigate. Some dark-versus-blue unit panels appear to depend on the unit's Emblem state, so compare the same scene and settings before reporting a color bug.

Testing so far has been on Windows 11 with an RTX 4060. Other GPUs, clean Windows installs, Linux and Steam Deck haven't been verified. TotK features and patches don't automatically work with Engage.

## Bring your own game files

The game isn't included. You'll need your own base game, 2.0.0 update, keys and firmware. Setup builds the executable on your PC and leaves your original dumps alone.

Please don't upload game files, keys, firmware, saves, extracted assets or generated code here. Alpha.5's built `engage.exe` contains game code and stays private. Development builds move that code into `engage_game.dll`, which also stays private; their separately built runtime contains no game code.

## Building from source

Follow [this guide](docs/building-engage.md) if you want to build or work on the port yourself. Source builds need developer tools; the setup ZIP already includes what players need.

For a source build, use `Run-Engage.cmd`. Keep `engage_game.dll` beside `engage.exe`; [DLL packaging](docs/engage-game-library.md) explains compatible runtime updates. Settings are in `engage.ini`, logs are in `logs/engage.log` next to the executable, and saves stay under `build/profile-engage`.

## Helping out

If something breaks, [open an issue](https://gitlab.com/engage-pc-recomp/engage-pc-recomp/-/issues/new). Include your version, GPU/driver, what you were doing and how to reproduce it. Check logs for personal paths before sharing them.

Want to contribute? Read [CONTRIBUTING.md](CONTRIBUTING.md). MRs go into **`dev`**. Small maintainer documentation edits don't need a PR.

See our [code of conduct](CODE_OF_CONDUCT.md), [security policy](SECURITY.md) and [accessibility statement](ACCESSIBILITY.md).

If you like the project, leave a star. Bug reports and help testing are welcome too.

[Porting notes](docs/engage-port.md) · [Making a release](docs/releasing-engage.md)

## Credits and license

This project is a fork of **TotK Recomp** by Valiantsin Dzerakh, starting from commit `f469c5a7745502357fc1664c04e02522fe92c42a`. Thanks to the upstream projects that made this possible. Their licenses and credits are kept in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

The port's code is under the [MIT License](LICENSE). Dependencies keep their own licenses; Nintendo game content isn't covered by this license. This is an independent fan project, not affiliated with Nintendo or Intelligent Systems. Fire Emblem and Nintendo Switch are their respective owners' trademarks.

The [original TotK README](docs/upstream-readme.md) is kept for reference. Use the Engage instructions here when installing this port.
