@echo off
rem KaZaA v2. revival launcher (Windows)
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "KaZaA" ".venv\Scripts\pythonw.exe" -m kazaa %*
) else (
  python -m kazaa %*
)
