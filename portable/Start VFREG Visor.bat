@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo VFREG-VISOR-SOFIA
echo Dashboard: http://127.0.0.1:8000
echo Keep this window open while collecting data.
echo Press Ctrl+C to stop the collector safely.
echo.

set "VFREG_INSTALL_SCRIPT=%~dp0Install-VFREGScheduledTask.ps1"
set "VFREG_DEPLOY_ROOT=%~dp0"
if "%VFREG_DEPLOY_ROOT:~-1%"=="\" set "VFREG_DEPLOY_ROOT=%VFREG_DEPLOY_ROOT:~0,-1%"

if exist "%VFREG_INSTALL_SCRIPT%" (
  "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%VFREG_INSTALL_SCRIPT%" -DeploymentRoot "%VFREG_DEPLOY_ROOT%"
  if errorlevel 1 (
    echo.
    echo ADVERTENCIA: No se pudo registrar o actualizar la tarea programada VFREG-VISOR-SOFIA ^(05:50^).
    echo El colector se iniciara de todos modos. Revise permisos o contacte a soporte.
    echo.
  )
)

"%~dp0VFREG-VISOR-SOFIA.exe" --config "%~dp0config.factory.json"

echo.
echo The VFREG collector has stopped.
pause
