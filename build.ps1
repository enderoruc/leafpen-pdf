# Builds dist\LeafpenPDF\LeafpenPDF.exe (a self-contained folder; no Python needed on the target PC).
# Exit codes are checked explicitly: PyInstaller logs to stderr, which PowerShell 5.1
# would otherwise treat as a terminating error.
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

& $py -m pytest -q (Join-Path $PSScriptRoot "tests")
if ($LASTEXITCODE -ne 0) { throw "Tests failed; not building." }

& $py -m PyInstaller --noconfirm --clean --windowed --name LeafpenPDF `
    --collect-submodules pyhanko --collect-submodules pyhanko_certvalidator `
    --exclude-module tkinter --exclude-module pytest `
    (Join-Path $PSScriptRoot "run.pyw")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }
Write-Host "Ready: dist\LeafpenPDF\LeafpenPDF.exe"
