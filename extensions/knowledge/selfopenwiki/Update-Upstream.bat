@echo off
setlocal
if "%~1"=="" goto usage
if /I "%~1"=="--apply" (
  if /I "%~2"=="--tag" (
    if "%~3"=="" goto usage
    if not "%~4"=="" goto usage
    node "%~dp0scripts\update-upstream.mjs" --apply "%~2" "%~3"
    exit /b %ERRORLEVEL%
  )
  if "%~3"=="" (
    node "%~dp0scripts\update-upstream.mjs" --apply "%~2"
    exit /b %ERRORLEVEL%
  )
  goto usage
)
if /I "%~1"=="--tag" (
  if "%~2"=="" goto usage
  if not "%~3"=="" goto usage
  node "%~dp0scripts\update-upstream.mjs" "%~1" "%~2"
  exit /b %ERRORLEVEL%
)
if not "%~2"=="" goto usage
node "%~dp0scripts\update-upstream.mjs" "%~1"
exit /b %ERRORLEVEL%

:usage
echo Usage: Update-Upstream.bat ^<40-character-commit^> ^| --tag ^<reviewed-annotated-tag^> 1>&2
echo        Update-Upstream.bat --apply ^<40-character-commit^> ^| --apply --tag ^<reviewed-annotated-tag^> 1>&2
exit /b 2
