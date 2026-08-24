@echo off
setlocal
cd /d "%~dp0"
where uv >nul 2>nul
if errorlevel 1 (
  echo ERROR: uv was not found on PATH.
  echo Run setup_new_notebook.bat first.
  pause
  exit /b 1
)
uv run --locked vfreg-visor --config config.factory.json
pause
