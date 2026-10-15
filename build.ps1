# Builds dist\LeafpenPDF\LeafpenPDF.exe (a self-contained folder; no Python needed on the target PC)
# and dist\LeafpenPDF-v<version>-win64.zip of that folder for distribution (its SHA-256 is printed).
# Exit codes are checked explicitly: PyInstaller logs to stderr, which PowerShell 5.1
# would otherwise treat as a terminating error.
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$assets = Join-Path $PSScriptRoot "leafpen\assets"

& $py -m pytest -q (Join-Path $PSScriptRoot "tests")
if ($LASTEXITCODE -ne 0) { throw "Tests failed; not building." }

& $py -m PyInstaller --noconfirm --clean --windowed --name LeafpenPDF `
    --icon (Join-Path $assets "icon.ico") --add-data "$assets;leafpen\assets" `
    --collect-submodules pyhanko --collect-submodules pyhanko_certvalidator `
    --exclude-module tkinter --exclude-module pytest `
    (Join-Path $PSScriptRoot "run.pyw")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

& $py (Join-Path $PSScriptRoot "tools\make_zip.py")
if ($LASTEXITCODE -ne 0) { throw "Zipping failed." }
Write-Host "Ready: dist\LeafpenPDF\LeafpenPDF.exe and the zip above"
