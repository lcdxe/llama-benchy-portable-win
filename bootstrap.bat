@echo off
rem ============================================================
rem  One-time bootstrap for a plain clone (this step needs network once).
rem  Creates .venv inside this folder and installs requirements.txt,
rem  so GUI.bat / run.bat work without the bundled python\ runtime.
rem  The portable bundle itself needs no bootstrap - just run GUI.bat.
rem ============================================================
cd /d "%~dp0"

set "TEMP=%~dp0.tmp"
set "TMP=%~dp0.tmp"
set "BASE_PY=python"
if exist "python\python.exe" set "BASE_PY=python\python.exe"

if not exist ".venv\Scripts\python.exe" (
  "%BASE_PY%" -m venv .venv
  if errorlevel 1 (
    echo Could not create .venv in this folder.
    exit /b 1
  )
)

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo pip install failed.
  exit /b 1
)

echo Done. Now use GUI.bat or run.bat.
exit /b 0
