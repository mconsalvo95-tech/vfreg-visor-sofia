@echo off
setlocal
cd /d "%~dp0"

echo VFREG-VISOR-SOFIA
echo Dashboard: http://127.0.0.1:8000
echo Keep this window open while collecting data.
echo Press Ctrl+C to stop the collector safely.
echo.

"%~dp0VFREG-VISOR-SOFIA.exe" --config "%~dp0config.factory.json"

echo.
echo The VFREG collector has stopped.
pause
