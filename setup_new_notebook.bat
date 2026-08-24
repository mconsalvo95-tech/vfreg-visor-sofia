@echo off
setlocal
cd /d "%~dp0"

echo VFREG NEW NOTEBOOK SETUP
echo Creating an isolated Python environment in .venv...

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m venv .venv
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo ERROR: Python 3.10 or newer was not found.
    echo Install Python, enable the Python launcher or PATH option, and retry.
    pause
    exit /b 1
  )
  python -m venv .venv
)

if errorlevel 1 (
  echo ERROR: Could not create the virtual environment.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :install_failed

".venv\Scripts\python.exe" -m pip install -e .
if errorlevel 1 goto :install_failed

echo.
echo Dependencies installed. Running the factory preflight...
".venv\Scripts\python.exe" preflight.py --config config.factory.json

echo.
echo Software setup is complete.
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

