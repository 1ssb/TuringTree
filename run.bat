@echo off
REM ---------------------------------------------------------------------------
REM run.bat - open RagIndex as a local app on Windows.
REM
REM Builds the web UI the first time, then starts the app and opens your browser.
REM Run scripts\setup.bat once beforehand to create the virtual-env and pull the
REM local models. Double-click this file, or run it from a terminal:
REM
REM     run.bat                 open the app
REM     run.bat --no-browser    serve without opening a browser
REM     run.bat --port 8765     pin a port
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" scripts\run.py %*
) else (
    python scripts\run.py %*
)
if errorlevel 1 pause
endlocal
