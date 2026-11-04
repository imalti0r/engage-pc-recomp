# Engage launcher

The setup bundle opens `Engage-Launcher.exe` for both Play and
Setup / Update. Keep the entire bundle together. The
alpha.5 and earlier setups do not contain this launcher.

The version pill at the top left reads `DEV · <version>` in a development
candidate and `v<version>` in a release ZIP. It describes the launcher package;
the supported game version remains Engage 2.0.0.

![Development launcher before a game is selected](screenshots/launcher.png)

## Play and setup

When no game is selected, **Set up Engage** offers **Use existing install**
(a folder containing `engage.exe` and `romfs-index.bin`) or **Set up from my game
files**. **Settings → Choose game folder** can switch installations later.
The installer opens in its own window and retains its existing input validation,
progress, recovery and update behavior. Packaged Setup installs `Engage-Launcher.exe`
beside the game and keeps the launcher, Python, extractor and rebuild tools in
`.launcher/` inside the game folder. Once these files are verified, Setup opens
the installed launcher and closes the original launcher/setup windows. The
completion message explains that the original extracted setup folder can be
deleted. Use the game folder's `Engage-Launcher.exe` for Play, settings, mods and
Setup / Update. Keep `.launcher/` with the game; source checkouts remain in place.

![Setup form with required files and optional extras](screenshots/setup.png)

Play requests foreground focus for the game while the launcher stays open behind
it. Settings, mod changes and save
backups are blocked until it exits. A game started separately must also be closed
before these actions. The executable can still be started directly.

## Launcher updates

The launcher checks published project releases in the background when it opens.
**Settings → Check for updates** also checks manually. No game paths or inputs
are sent. Offline checks never block Play. Unpublished branches and PR builds are
not announced as updates.

An available update offers **Update now** and **Later**. Update now asks once,
downloads the Windows setup ZIP, compares its SHA-256 with the release's
`SHA256SUMS`, and validates/extracts it into a new sibling folder. A corrupt or
unsafe package leaves the running bundle unchanged. Downloads can be cancelled.

The new bundled Python/UI imports must pass a startup check before activation.
The previous bundle is kept. Existing launcher shortcuts follow a local redirect
to the new, verified launcher; the old executable files are retained for recovery.
To return to that old launcher manually, remove its `launcher-update.json`.

The launcher then restarts and runs the existing game-update pipeline against the
remembered installation. Cached extraction/generated code are reused when valid;
a code change may require a local rebuild. If inputs/cache are missing, Setup
asks for the required files. Saves, mods and settings are retained by that pipeline.
Updates from source checkouts remain a Git operation.

For an installed launcher, these versioned tool packages remain inside the game
folder's `.launcher/`. The game folder's `Engage-Launcher.exe` selects the active
package. Setup verifies the new installed copy before switching to it, so the
original download/extracted setup folder is no longer needed afterward. Keep the
installed tool folders; deleting `.launcher/` breaks the installed launcher.

## Local game icon

The setup/launcher download and public runtime embed only the original host E
icon. Setup converts `icon.jpg` from the player's extracted control data into
`engage.ico` beside the installed game. The running game and launcher load that
local icon for their windows/taskbar; the launcher falls back to its host icon
until an installation is selected. No extracted icon is copied into the setup
bundle or public executable. The executable file's own Explorer icon stays generic.

## Settings and saves

The settings page writes only the values you change to `engage.ini`, preserving
other settings and comments. Environment variables still override the file.
More controls remain available with F1 in-game.

Save loading happens in the game's title menu. **Open folder** opens
`profile/save`; **Back up** makes a ZIP in `save-backups`, including committed
saves and pending save transactions. It never restores or overwrites a save.
These actions use the portable profile beside the game executable.

## RomFS mods

Import a ZIP or an extracted mod folder through **Mods**, or put each extracted
mod in its own folder beside the game's executable:

```text
mods/
  My Mod/
    romfs/
      Data/...
```

The following wrappers inside a mod folder are also recognized:

- `0100A6301214E000/romfs/`
- `contents/0100A6301214E000/romfs/`
- `atmosphere/contents/0100A6301214E000/romfs/`

Mods replace or add whole files without changing `romfs.bin`. No custom manifest
is needed. The first folder alphabetically wins when enabled mods provide the same
file. Paths retain their case. The launcher reports overridden files; the in-game
F1 Mods tab also reports loaded replacements and additions.

The launcher Mods page includes name search and filters for enabled, disabled and
attention-needed mods. Select a row for compatibility and file-overlap details.
Unsupported mods cannot be toggled. The F1 Mods page groups mods by what is active
in the current session; toggles show a restart notice until the next launch.

Toggle a mod in the launcher before Play, or in the F1 Mods tab and restart the
game. Files must stay unchanged during a session; a changed file requires a
restart. Folder links and linked files are rejected. ZIP import rejects traversal
and links and never overwrites an installed mod.

Code patches (`exefs`, IPS/pchtxt), Cobalt plugins and mods requiring those
components are unsupported. A mixed mod can load its RomFS files, with a warning
that its code features will not work. A valid folder layout does not establish
compatibility with Engage 2.0.0 or with other mods.

Local validation used ZelkovPropaganda's **Skip Intro Straight to Title Screen**
(https://gamebanana.com/mods/442722). Both 964-byte video replacements were read
byte for byte through the runtime, the short replacement played, and the title
screen was reached. The mod is a local test input, not part of the release.
Gameplay mods, Cobalt and a full modded playthrough remain untested.

## Development

Run `python -m engage_setup.gui --dest <install>` to open the launcher, or add
`--setup` for the wizard. `--selftest --shots <directory>` captures each page.
The launcher uses Pillow, pinned in `tools/requirements-installer.txt`.
Artwork provenance is recorded in `engage_setup/art/README.md`; no game artwork
is extracted or bundled by the launcher.

`engage.exe --probe-mods` compares each selected overlay against its host file,
including size, contents, end-of-file and read-only access. Synthetic tests cover
folder layouts, priority, enablement, unsafe archives and save preservation.
