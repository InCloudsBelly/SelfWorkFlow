@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-selfworkflow.ps1" %*
exit /b %errorlevel%
