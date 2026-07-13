# scripts/setup.ps1 — Windows (PowerShell) setup wrapper for RagIndex.
#
# The real, cross-platform logic lives in scripts/setup.py so Windows, macOS,
# and Linux all run the exact same steps. This wrapper just finds a Python 3
# interpreter and hands off (forwarding any extra flags, e.g. --skip-ollama).
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$exe = "python"
$pre = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    $exe = "py"; $pre = @("-3")
} elseif (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    if (Get-Command python3 -ErrorAction SilentlyContinue) {
        $exe = "python3"
    } else {
        Write-Error "Python 3 is required but was not found. Install Python 3.10+ from https://python.org and re-run."
        exit 1
    }
}

& $exe @pre "scripts/setup.py" @args
exit $LASTEXITCODE
