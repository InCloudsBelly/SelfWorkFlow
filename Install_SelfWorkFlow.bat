@echo off
setlocal
set "GIT_TERMINAL_PROMPT=0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-selfworkflow.ps1" %*
exit /b %errorlevel%
