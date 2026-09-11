@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "VFREG_INSTALL_SCRIPT=%~dp0Install-VFREGScheduledTask.ps1"
set "VFREG_DEPLOY_ROOT=%~dp0"
if "%VFREG_DEPLOY_ROOT:~-1%"=="\" set "VFREG_DEPLOY_ROOT=%VFREG_DEPLOY_ROOT:~0,-1%"
set "VFREG_TEST_TASK=VFREG-VISOR-SOFIA-WAKE-TEST"
set "VFREG_PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
set "VFREG_CONFIG=config.factory.json"
if exist "%~dp0config.json" if not exist "%~dp0config.factory.json" set "VFREG_CONFIG=config.json"

echo VFREG - Prueba de despertar a una hora elegida
echo.
echo Esto NO cambia la tarea de produccion VFREG-VISOR-SOFIA ^(05:50^).
echo Solo crea o quita la tarea %VFREG_TEST_TASK%.
echo.

if not exist "%VFREG_INSTALL_SCRIPT%" goto :err_missing_script

if /i "%VFREG_WAKE_TEST_ACTION%"=="remove" goto :remove_task
if /i "%VFREG_WAKE_TEST_ACTION%"=="register" goto :ask_time

echo 1. Programar una prueba ^(ingresar hora HH:mm, ejemplo 15:35^)
echo 2. Quitar la tarea de prueba
echo.
set /p VFREG_CHOICE=Elija 1 o 2: 
if "%VFREG_CHOICE%"=="1" goto :ask_time
if "%VFREG_CHOICE%"=="2" goto :remove_task
echo Opcion no valida.
call :maybe_pause
exit /b 1

:ask_time
if not defined VFREG_WAKE_TEST_TIME (
  set /p VFREG_WAKE_TEST_TIME=Hora de prueba HH:mm ^(24 horas, ejemplo 15:35^): 
)
if not defined VFREG_WAKE_TEST_TIME goto :err_time
if "%VFREG_WAKE_TEST_TIME%"=="" goto :err_time
if not exist "%~dp0VFREG-VISOR-SOFIA.exe" goto :err_missing_exe
if not exist "%~dp0%VFREG_CONFIG%" goto :err_missing_config

echo.
echo Registrando %VFREG_TEST_TASK% a las %VFREG_WAKE_TEST_TIME%...
echo Config: %VFREG_CONFIG%
echo Sin disparador de inicio de sesion ^(solo esa hora, con WakeToRun^).
echo.

"%VFREG_PS%" -NoProfile -ExecutionPolicy Bypass -File "%VFREG_INSTALL_SCRIPT%" -DeploymentRoot "%VFREG_DEPLOY_ROOT%" -TaskName "%VFREG_TEST_TASK%" -ConfigName "%VFREG_CONFIG%" -DailyStartTime "%VFREG_WAKE_TEST_TIME%" -NoLogonTrigger
if errorlevel 1 goto :err_register

echo.
echo Listo. Para probar el despertar:
echo 1. En planta, o en una carpeta de prueba, ejecute antes "Configurar despertar del PC.bat"
echo    ^(en una PC personal, restaure la politica de energia despues de la prueba^).
echo 2. Ponga la PC a dormir unos minutos ANTES de %VFREG_WAKE_TEST_TIME%.
echo 3. Confirme que Windows desperto y el colector arranco.
echo 4. Vuelva a este BAT y elija 2 para quitar la tarea de prueba.
echo.
echo La tarea de produccion 05:50 no se modifico.
call :maybe_pause
exit /b 0

:remove_task
echo.
echo Quitando %VFREG_TEST_TASK%...
"%VFREG_PS%" -NoProfile -ExecutionPolicy Bypass -File "%VFREG_INSTALL_SCRIPT%" -Remove -TaskName "%VFREG_TEST_TASK%"
if errorlevel 1 goto :err_remove
echo.
echo Tarea de prueba quitada. VFREG-VISOR-SOFIA ^(05:50^) no se toco.
call :maybe_pause
exit /b 0

:err_missing_script
echo ERROR: No se encontro Install-VFREGScheduledTask.ps1 en esta carpeta.
call :maybe_pause
exit /b 2

:err_missing_exe
echo ERROR: No se encontro VFREG-VISOR-SOFIA.exe en esta carpeta.
echo Ejecute este BAT desde la carpeta extraida del ZIP portable, o desde una
echo copia de prueba que incluya el ejecutable.
call :maybe_pause
exit /b 2

:err_missing_config
echo ERROR: No se encontro %VFREG_CONFIG% en esta carpeta.
call :maybe_pause
exit /b 2

:err_time
echo ERROR: Indique una hora en formato HH:mm ^(ejemplo 15:35, no 7:30^).
call :maybe_pause
exit /b 1

:err_register
echo.
echo ERROR: No se pudo registrar la tarea de prueba. Revise la hora HH:mm y permisos.
call :maybe_pause
exit /b 1

:err_remove
echo.
echo ERROR: No se pudo quitar la tarea de prueba.
call :maybe_pause
exit /b 1

:maybe_pause
if /i "%VFREG_BAT_NO_PAUSE%"=="1" exit /b 0
pause
exit /b 0
