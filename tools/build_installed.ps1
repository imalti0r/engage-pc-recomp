# Build the Engage runtime from the INSTALLED game folder and deploy engage.exe into it.
#
# The installed folder (E:\Folders\Games\Fire Emblem Engage) already holds everything the runtime needs at run time:
# romfs\ (romfs.bin + index.json), exefs\, fonts\, aoc\, profile\, totk_xlate.exe, engage_game.dll. Only the runtime
# binary changes during development, so this rebuilds engage.exe and copies it over the installed one.
#
#   powershell -File tools\build_installed.ps1              # rebuild the runtime, deploy it, and start the game
#   powershell -File tools\build_installed.ps1 -NoRun       # rebuild and deploy only
#   powershell -File tools\build_installed.ps1 -GameDir D:\Other\Engage
#
# The game's own resources are never modified: only engage.exe is replaced.
param(
    [string]$GameDir = 'E:\Folders\Games\Fire Emblem Engage',
    [switch]$NoRun
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path (Join-Path $GameDir 'romfs\romfs.bin'))) {
    throw "no installed game at $GameDir (expected romfs\romfs.bin). Pass -GameDir <folder>."
}

# stop a running instance: the linker cannot overwrite a mapped engage.exe
Get-Process engage -ErrorAction SilentlyContinue | ForEach-Object { $_.Kill(); $_.WaitForExit(5000) }
Start-Sleep -Milliseconds 500

& .venv\Scripts\python.exe `
    tools\build_engage.py `
    --extracted $GameDir `
    --gen build\generated\engage-v200-cont `
    --out build\engage-v200-cont `
    --romfs (Join-Path $GameDir 'romfs') `
    --profile (Join-Path $GameDir 'profile') `
    --toolchain toolchain/engage/llvm `
    --deps toolchain/engage/runtime/deps `
    --ninja toolchain/engage/ninja.exe `
    --runtime runtime `
    --jobs 8
if ($LASTEXITCODE -ne 0) { throw "build failed (exit $LASTEXITCODE)" }

$built = Join-Path $root 'build\engage-v200-cont\engage.exe'
if (-not (Test-Path $built)) { throw 'the build produced no engage.exe' }
$target = Join-Path $GameDir 'engage.exe'
Copy-Item $built $target -Force
$size = [math]::Round((Get-Item $target).Length / 1MB, 1)
Write-Host "deployed engage.exe ($size MiB) to $GameDir"

if (-not $NoRun) {
    Start-Process -FilePath $target -WorkingDirectory $GameDir
    Write-Host 'started the game'
}
