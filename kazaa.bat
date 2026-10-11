@echo off
rem KazaA v2. revival launcher (Windows)
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "KazaA" ".venv\Scripts\pythonw.exe" -m kazaa %*
) else (
  python -m kazaa %*
)
