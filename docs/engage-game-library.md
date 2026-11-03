# Engage runtime and game DLL

Development builds separate the public Windows runtime (`engage.exe`) from
`engage_game.dll`, which setup builds from the player's Engage 2.0.0 files.
Alpha.5 downloads still use the earlier single-executable layout.

The DLL contains the lifted game functions, their dispatch tables, the verified
game-file hashes, RomFS identity, patch definitions and default local paths.
The runtime contains graphics, audio, input, settings, filesystem and kernel code.
Its icon is an original monogram rather than extracted game artwork.

## Updates and compatibility

The runtime loads `engage_game.dll` beside its own executable. The DLL reports an
ABI version and a compatibility ID derived from the CPU/SIMD contract, generator,
patch table and exported host services. Missing or incompatible libraries stop
with a message asking the player to run setup again. A loaded DLL stays mapped
until the process exits because dispatch tables retain pointers into it.

The first update from the single-executable layout builds the DLL once. Setup
keeps original game data, settings and profiles. It stages the new EXE/DLL pair
and restores the previous pair if a replacement fails. Close the game before
updating.

For later compatible updates, setup checks the generated-input fingerprint and
DLL SHA-256, reuses the existing DLL and installs the bundled runtime. CPU layout,
generator or game-patch changes require rebuilding the DLL. A runtime implementation
fix alone does not change the compatibility ID. Generated C is retained so a
necessary rebuild does not require extracting the game again.

## Build

The normal commands in [building-engage.md](building-engage.md) build both files.
To build only the public runtime without game inputs:

```powershell
.venv/Scripts/python tools/build_engage.py --runtime-only --out build/engage-runtime
```

That writes `engage.exe` and `engage.json`, its compatibility ID and file hash.
Pass `--runtime-exe build/engage-runtime/engage.exe` with a normal game build to
use that checked runtime and compile only the private game DLL. Keep the JSON
beside the prebuilt executable. The release builder does this automatically.

Never distribute `engage_game.dll`, generated C, game assets, extracted icons,
profiles or an older monolithic `engage.exe`. Only the independently built public
runtime and source/tooling are suitable for a setup package.
