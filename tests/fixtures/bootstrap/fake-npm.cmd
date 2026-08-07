@echo off
setlocal

if not defined FAKE_NPM_VERSION set "FAKE_NPM_VERSION=1.2.3"
if not defined FAKE_NPM_INTEGRITY set "FAKE_NPM_INTEGRITY=sha512-U2VsZldvcmtGbG93RmFrZUludGVncml0eQ=="
if not defined FAKE_NPM_INSTALLED_VERSION set "FAKE_NPM_INSTALLED_VERSION=%FAKE_NPM_VERSION%"
if not defined FAKE_NPM_INSTALLED_INTEGRITY set "FAKE_NPM_INSTALLED_INTEGRITY=%FAKE_NPM_INTEGRITY%"
if not defined FAKE_NPM_CLI_VERSION_OUTPUT set "FAKE_NPM_CLI_VERSION_OUTPUT=codex-cli %FAKE_NPM_INSTALLED_VERSION%"

if /I "%~1"=="view" goto view
if /I "%~1"=="install" goto install

>&2 echo fake-npm: unsupported command %~1
exit /b 64

:view
if /I "%FAKE_NPM_FAIL_COMMAND%"=="view" exit /b 41
echo {"version":"%FAKE_NPM_VERSION%","dist.integrity":"%FAKE_NPM_INTEGRITY%"}
exit /b 0

:install
if defined FAKE_NPM_INSTALL_MARKER type nul > "%FAKE_NPM_INSTALL_MARKER%"
if /I "%FAKE_NPM_FAIL_COMMAND%"=="install" exit /b 42
if /I "%FAKE_NPM_SKIP_ARTIFACTS%"=="1" exit /b 0
set "FAKE_NPM_PREFIX="

:parse-install-arguments
if "%~1"=="" goto create-install-tree
if /I "%~1"=="--prefix" goto capture-prefix
shift
goto parse-install-arguments

:capture-prefix
set "FAKE_NPM_PREFIX=%~2"
shift
shift
goto parse-install-arguments

:create-install-tree
if not defined FAKE_NPM_PREFIX exit /b 65
mkdir "%FAKE_NPM_PREFIX%\node_modules\@openai\codex\bin" 2>nul
mkdir "%FAKE_NPM_PREFIX%\node_modules\.bin" 2>nul
> "%FAKE_NPM_PREFIX%\node_modules\@openai\codex\package.json" echo {"name":"@openai/codex","version":"%FAKE_NPM_INSTALLED_VERSION%"}
> "%FAKE_NPM_PREFIX%\node_modules\@openai\codex\bin\codex.js" echo fake-codex-cli
> "%FAKE_NPM_PREFIX%\package-lock.json" echo {"lockfileVersion":3,"packages":{"node_modules/@openai/codex":{"name":"@openai/codex","version":"%FAKE_NPM_INSTALLED_VERSION%","integrity":"%FAKE_NPM_INSTALLED_INTEGRITY%"}}}
if /I "%FAKE_NPM_SKIP_CLI%"=="1" exit /b 0
> "%FAKE_NPM_PREFIX%\node_modules\.bin\codex.cmd" echo @echo off
>> "%FAKE_NPM_PREFIX%\node_modules\.bin\codex.cmd" echo echo %FAKE_NPM_CLI_VERSION_OUTPUT%
if defined FAKE_NPM_CLI_EXIT_CODE >> "%FAKE_NPM_PREFIX%\node_modules\.bin\codex.cmd" echo exit /b %FAKE_NPM_CLI_EXIT_CODE%
exit /b 0
