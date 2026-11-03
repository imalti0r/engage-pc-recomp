# Building Engage PC Recomp

These instructions are for building the Windows port yourself. If you just want to play, use the [setup guide](installing-engage.md).

Use a writable folder with plenty of space. The extracted game and packed RomFS each take about 16 GB, before counting your dumps, tools and build files. Use the Engage commands below; TotK's patch lists are for a different game.

You'll need Git, Python 3.12 and 3.14, the .NET 10 SDK, Visual Studio C++ build tools for the shader translator, and Windows PowerShell. To run the game, you need an x86-64-v3 CPU with AVX2 and a Vulkan 1.3 GPU. Testing so far has been on an RTX 4060.

## Prepare tools

From the repository root in PowerShell:

```powershell
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r tools/requirements-engage-lifter.txt
py -3.14 -m venv .venv-py314
.venv-py314/Scripts/python -m pip install -r tools/requirements-installer.txt
.venv-py314/Scripts/python tools/setup_engage_toolchain.py

dotnet publish tools/nx_extract/nx_extract.csproj -c Release --artifacts-path build/nx-extract-artifacts -o toolchain/nx_extract --no-self-contained
.venv/Scripts/python tools/build_xlate.py
```

Toolchain downloads are checked against pinned hashes. The extractor uses LibHac 0.19.0.

## Supply your own inputs

Copy `config.engage.example.toml` to `config.local.toml` and fill in your local file paths: base game, 2.0.0 update, keys and extracted firmware folder. DLC is optional; leave out the DLC entries you aren't using. The update needs a valid ticket or your matching title key. Game files, firmware and keys aren't provided here.

```powershell
.venv-py314/Scripts/python tools/extract_engage.py
.venv-py314/Scripts/python tools/extract_fonts.py
.venv/Scripts/python tools/pack_engage_romfs.py --source build/extracted/engage-v200/RomFS --out build/extracted/engage-v200/packed-romfs
```

The extractor checks the packages, update version and content integrity. The packer won't overwrite an existing output. If a step stops halfway through, check what it left behind before retrying. Keep your dumps and profile safe.

## Recompile locally

```powershell
.venv/Scripts/python recomp/gen.py --exefs build/extracted/engage-v200/ExeFS --out generated/engage-v200-cont --patches recomp/patches-engage-v200.txt --no-callee-saved-trust --continuations
.venv/Scripts/python tools/build_engage.py --gen generated/engage-v200-cont --out build/engage-v200-cont --jobs 12
.\Run-Engage.cmd
```

Lower `--jobs` if your machine is running out of memory. The first build takes a while.
Development builds produce a public `engage.exe` runtime and a private `engage_game.dll`
beside it. Both are required to play. Generated game code and the DLL stay private.
See [DLL builds and compatible updates](engage-game-library.md).

The launcher sets Vulkan and the shared-font path, with the experimental recorder turned off. **F1** opens settings, **F10** changes the performance overlay, and **F11** toggles fullscreen. Keep `build/profile-engage` when rebuilding—that's your player data.

The Engage patch table enables the game's 60 FPS timing path and checks the main
module's build ID and original instruction before generation. F1's Game tab offers
30 FPS (original timing) or 60 FPS; restart after changing it. Rates above 60 are
unsupported. Presentation VSync controls how frames reach the display; disabling
it alone does not unlock the game's frame rate. Alpha.3 does not include this patch.

The menu supports Engage-specific [game output resolution and 3D render scale](engage-resolution.md).
It hides inherited controls that currently have no Engage
implementation: field of view,
TotK's real-time/cloth/high-FPS patches, Xbox prompt graphics and the TotK LOD
guard. Virtual core preemption is also hidden because Engage uses cooperative
boundaries for GC snapshots. The gyro-aiming control is hidden pending verification
of an Engage gameplay feature that uses it. The performance overlay omits the unmeasured Unity
scene resolution instead of showing TotK's dimensions.

Window size, fullscreen, display upscaling/sharpening, color adjustment, volume,
input bindings and the general Vulkan controls remain available. Button mapping
still supports Nintendo and Xbox layouts; in-game button images stay Nintendo.
Features useful to Engage can return when they have an implementation and tests.

## Check changes

```powershell
.venv/Scripts/python tools/check_content.py
.venv/Scripts/python -m unittest discover -s tests -p "engage*_test.py"
.venv/Scripts/python tests/extract_engage_test.py
.venv/Scripts/python tests/continuations_test.py
build/engage-v200-cont/engage.exe --selftest
build/engage-v200-cont/engage.exe --probe-menu-font
build/engage-v200-cont/engage.exe --probe-audout
build/engage-v200-cont/engage.exe --probe-engage-fs
build/engage-v200-cont/engage.exe --probe-engage-input
```

The Engage filesystem/DLC probe expects both DLC packages to be installed.

For lifter changes, also run the differential tests in [the engine build guide](building.md). Passing CI doesn't tell us whether a whole playthrough works. Check [the porting notes](engage-port.md) for what has actually been tested.
