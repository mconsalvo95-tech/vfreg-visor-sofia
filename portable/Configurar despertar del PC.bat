@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "VFREG_WAKE_SCRIPT=%~dp0Enable-VFREGWakeTimers.ps1"
set "VFREG_DEPLOY_ROOT=%~dp0"
if "%VFREG_DEPLOY_ROOT:~-1%"=="\" set "VFREG_DEPLOY_ROOT=%VFREG_DEPLOY_ROOT:~0,-1%"
set "VFREG_WAKE_EXITFILE=%TEMP%\vfreg-wake-exit-%RANDOM%.txt"
set "VFREG_PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if defined VFREG_BAT_POWERSHELL set "VFREG_PS=%VFREG_BAT_POWERSHELL%"

echo VFREG - Configurar despertador RTC (solo corriente AC)
echo.
echo Este paso pide permiso de administrador (UAC) para habilitar
echo despertadores de temporizador RTC mientras la PC usa corriente.
echo No cambia la configuracion con bateria.
echo.
echo Si IT no lo autoriza, cancele UAC y contacte soporte.
echo.

if not exist "%VFREG_WAKE_SCRIPT%" goto :err_missing_script

del /q "%VFREG_WAKE_EXITFILE%" 2>nul

call "%VFREG_PS%" -NoProfile -ExecutionPolicy Bypass -Command "$q = [char]34; $esc = { param($s) if ($s -match $q) { throw 'Embedded double quote in path.' }; $q + $s + $q }; $argLine = '-NoProfile -ExecutionPolicy Bypass -File ' + (& $esc $env:VFREG_WAKE_SCRIPT) + ' -DeploymentRoot ' + (& $esc $env:VFREG_DEPLOY_ROOT) + ' -ExitFile ' + (& $esc $env:VFREG_WAKE_EXITFILE); $p = Start-Process -FilePath $env:VFREG_PS -Verb RunAs -Wait -PassThru -ArgumentList $argLine; if (Test-Path -LiteralPath $env:VFREG_WAKE_EXITFILE) { exit 0 }; if ($null -eq $p -or $p.ExitCode -eq 1223) { exit 1223 }; exit 0"

set "VFREG_PS_EXIT=%ERRORLEVEL%"
set "VFREG_RC="
if exist "%VFREG_WAKE_EXITFILE%" (
  set /p VFREG_RC=<"%VFREG_WAKE_EXITFILE%"
  del /q "%VFREG_WAKE_EXITFILE%" 2>nul
)

if defined VFREG_RC goto :validate_sentinel
if "%VFREG_PS_EXIT%"=="1223" goto :err_uac
goto :err_elevation

:validate_sentinel
echo.%VFREG_RC%| findstr /r "^[0-9][0-9]*$" >nul
if errorlevel 1 goto :err_elevation
if %VFREG_RC% GEQ 256 goto :err_elevation
if "%VFREG_RC%"=="1223" goto :err_uac
if not "%VFREG_RC%"=="0" goto :err_generic
goto :wake_ok

:err_missing_script
echo ERROR: No se encontro Enable-VFREGWakeTimers.ps1 en esta carpeta.
call :maybe_pause
exit /b 2

:err_elevation
echo.
echo ERROR: No se pudo completar la elevacion de administrador (UAC).
echo Si cancelo el aviso de Windows, vuelva a intentarlo y pulse Si.
echo Si el aviso no aparecio o el proceso elevado no respondio, contacte soporte.
call :maybe_pause
exit /b 1259

:err_uac
echo.
echo UAC cancelado o acceso denegado. No se cambio la politica de energia.
call :maybe_pause
exit /b 1223

:err_generic
echo.
echo ERROR: No se pudo configurar el despertador RTC. Codigo %VFREG_RC%.
echo Revise el mensaje anterior o ejecute ValidateOnly con soporte.
call :maybe_pause
exit /b %VFREG_RC%

:wake_ok
echo.
echo Listo: despertador RTC habilitado para corriente AC.
echo La pantalla puede permanecer apagada tras un despertar programado.
echo Respaldo en data\vfreg-wake-timer-backup.json
echo.
call :maybe_pause
exit /b 0

:maybe_pause
if /i "%VFREG_BAT_NO_PAUSE%"=="1" exit /b 0
pause
exit /b 0
