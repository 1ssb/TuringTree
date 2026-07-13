@echo off
REM scripts\setup.bat — Windows (cmd.exe) setup wrapper for RagIndex.
REM The real, cross-platform logic lives in scripts\setup.py; this just finds a
REM Python 3 interpreter and forwards any extra flags (e.g. --skip-ollama).

cd /d "%~dp0.."

where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3 scripts\setup.py %*
    exit /b %ERRORLEVEL%
)

where python >nul 2>nul
if %ERRORLEVEL%==0 (
    python scripts\setup.py %*
    exit /b %ERRORLEVEL%
)

echo Python 3 is required but was not found. Install Python 3.10+ from https://python.org and re-run.
exit /b 1
