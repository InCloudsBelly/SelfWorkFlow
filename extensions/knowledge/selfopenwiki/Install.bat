@echo off
setlocal

where node >nul 2>nul
if errorlevel 1 (
  >&2 echo SelfOpenWiki install error: Node.js 22 or newer is required.
  exit /b 1
)

node "%~dp0scripts\install.mjs" %*
set "install_exit_code=%errorlevel%"
exit /b %install_exit_code%
