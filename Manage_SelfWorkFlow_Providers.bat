@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\manage-selfworkflow-providers.ps1" %*
exit /b %errorlevel%
