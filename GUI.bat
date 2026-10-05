@echo off
rem ============================================================
rem  llama-benchy GUI launcher (portable edition) - keep this file pure ASCII.
rem  cmd reads .bat with the system ANSI codepage (GBK on Chinese Windows),
rem  so non-ASCII comments here would be mis-parsed as commands.
rem
rem  Opens the tkinter control panel (presets tab + compare tab).
rem  Start your inference server first, then double-click this file.
rem  GUI crashes are logged to gui\gui.log.
rem ============================================================
cd /d "%~dp0"

set "PYTHONPATH=%~dp0"
set "HF_HUB_OFFLINE=1"
set "HF_HOME=%~dp0.hf"
set "TEMP=%~dp0.tmp"
set "TMP=%~dp0.tmp"

rem interpreter: bundled portable runtime > local .venv > system python
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if exist "python\python.exe" set "PY=python\python.exe"

start "" "%PY%" gui\bench_gui.py 1> gui\gui.log 2>&1
exit /b 0