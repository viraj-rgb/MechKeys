# Builds dist\MechKeys\MechKeys.exe (one folder, no console window).
# One-folder instead of one-file: a single process, faster start, and nothing
# re-extracted to %TEMP% (~77 MB) on every launch.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python -m pip install -r requirements-dev.txt --quiet
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed; not building." }

python -m mechkeys.icon
python -m PyInstaller --noconfirm --clean --windowed --onedir `
    --name MechKeys `
    --icon assets\mechkeys.ico `
    --add-data "sounds;sounds" `
    --hidden-import pystray._win32 `
    MechKeys.pyw
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

if (Test-Path dist\MechKeys.exe) { Remove-Item dist\MechKeys.exe }  # old one-file build
Write-Host "Built $(Resolve-Path dist\MechKeys\MechKeys.exe)"

# Release zip: the app folder plus licences, as dist\MechKeys-Windows.zip.
Copy-Item LICENSE, THIRD_PARTY_NOTICES.md, README.md -Destination dist\MechKeys -Force
$zip = "dist\MechKeys-Windows.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path dist\MechKeys -DestinationPath $zip -CompressionLevel Optimal
Write-Host ("Packaged {0} ({1:N1} MB)" -f (Resolve-Path $zip), ((Get-Item $zip).Length / 1MB))
