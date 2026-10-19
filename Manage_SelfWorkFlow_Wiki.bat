@echo off
setlocal
if /i "%~1"=="register" goto host
if /i "%~1"=="doctor" goto host
where node >nul 2>nul
if errorlevel 1 (
  >&2 echo SelfWorkFlow Wiki: Node.js 22 or newer is required.
  exit /b 1
)
node "%~dp0extensions\knowledge\selfopenwiki\scripts\manage-wiki.mjs" %*
exit /b %errorlevel%
:host
if not exist "%LOCALAPPDATA%\SelfWorkFlow\bin\selfworkflow.cmd" (
  >&2 echo SelfWorkFlow Wiki: install the knowledge workflow first.
  exit /b 1
)
call "%LOCALAPPDATA%\SelfWorkFlow\bin\selfworkflow.cmd" wiki %* --repository "%~dp0."
exit /b %errorlevel%
