@echo off
setlocal
cd /d "%~dp0"

echo VFREG DEVELOPMENT COMPUTER SETUP
echo.

where uv >nul 2>nul
if errorlevel 1 (
  echo ERROR: uv was not found on PATH.
  echo Install uv from https://docs.astral.sh/uv/getting-started/installation/
  echo Then open a new PowerShell window and run this file again.
  pause
  exit /b 1
)

uv sync --locked
if errorlevel 1 goto :install_failed

echo.
echo Locked environment installed. Running the factory preflight...
uv run --locked python preflight.py --config config.factory.json
if errorlevel 1 goto :preflight_failed

echo.
echo Development setup is complete.
echo The Ethernet adapter must use 192.168.1.1 / 255.255.255.0 with no gateway.
echo See NEW_NOTEBOOK_SETUP.md before connecting to the VFREG.
pause
exit /b 0

:install_failed
echo.
echo ERROR: Dependency installation failed.
echo Internet access is required during this one-time setup.
pause
exit /b 1

:preflight_failed
echo.
echo ERROR: Dependencies are installed, but the factory preflight reported a problem.
echo Review the messages above before connecting to the VFREG.
pause
exit /b 1
