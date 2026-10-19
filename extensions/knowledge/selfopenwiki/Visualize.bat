@echo off
setlocal

where node >nul 2>nul
if errorlevel 1 (
  >&2 echo SelfOpenWiki visualization error: Node.js 22 or newer is required.
  exit /b 1
)

node "%~dp0scripts\visualize.mjs" %*
set "visualize_exit_code=%errorlevel%"
exit /b %visualize_exit_code%
