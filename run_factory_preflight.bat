@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" preflight.py --config config.factory.json
  echo.
  pause
  exit /b
)
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 preflight.py --config config.factory.json
) else (
  python preflight.py --config config.factory.json
)
echo.
pause
