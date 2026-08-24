@echo off
setlocal
cd /d "%~dp0"
where uv >nul 2>nul
if errorlevel 1 (
  echo ERROR: uv was not found on PATH.
  echo See NEW_NOTEBOOK_SETUP.md.
  pause
  exit /b 1
)
uv sync --locked
pause
