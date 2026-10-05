@echo off
rem ============================================================
rem  llama-benchy command-line run script (portable edition) - pure ASCII.
rem  Edit the three variables below, then double-click this file.
rem  Environment is isolated: no proxy, no writes outside this folder.
rem ============================================================
cd /d "%~dp0"

rem ---- environment isolation ----
set "HTTP_PROXY="
set "HTTPS_PROXY="
set "NO_PROXY=localhost,127.0.0.1"
set "HF_HUB_OFFLINE=1"
set "HF_HOME=%~dp0.hf"
set "TEMP=%~dp0.tmp"
set "TMP=%~dp0.tmp"
set "PYTHONPATH=%~dp0"

rem ---- edit your parameters here ----
set "BASE_URL=http://127.0.0.1:8080/v1"
set "MODEL=qwen"
set "ARGS=--runs 2 --pp 512 --tg 512 --depth 512 4096 8096 --latency-mode generation"

rem ---- interpreter: bundled portable runtime > local .venv > system python ----
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if exist "python\python.exe" set "PY=python\python.exe"

rem ---- wait up to 120 s for the server to accept connections ----
"%PY%" tools\wait_port.py 127.0.0.1 8080 120 || (
  echo Server not reachable on 127.0.0.1:8080 within 120 s. Start it first.
  exit /b 1
)

"%PY%" -m llama_benchy --base-url %BASE_URL% --model %MODEL% %ARGS%
exit /b %ERRORLEVEL%