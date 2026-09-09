@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Mock-BatPowerShell.ps1" %*
