@echo off
setlocal

where node >nul 2>nul
if errorlevel 1 (
  >&2 echo SelfOpenWiki setup error: Node.js 22 or newer is required.
  exit /b 1
)

node "%~dp0scripts\setup.mjs" %*
set "setup_exit_code=%errorlevel%"
exit /b %setup_exit_code%
