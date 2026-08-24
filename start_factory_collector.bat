@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" app.py --config config.factory.json
  pause
  exit /b
)
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 app.py --config config.factory.json
) else (
  python app.py --config config.factory.json
)
pause
