@echo off
setlocal

if not defined FAKE_NPM_VERSION set "FAKE_NPM_VERSION=1.2.3"
if not defined FAKE_NPM_INTEGRITY set "FAKE_NPM_INTEGRITY=sha512-U2VsZldvcmtGbG93RmFrZUludGVncml0eQ=="
if not defined FAKE_NPM_INSTALLED_VERSION set "FAKE_NPM_INSTALLED_VERSION=%FAKE_NPM_VERSION%"
if not defined FAKE_NPM_INSTALLED_INTEGRITY set "FAKE_NPM_INSTALLED_INTEGRITY=%FAKE_NPM_INTEGRITY%"
if not defined FAKE_NPM_CLI_VERSION_OUTPUT set "FAKE_NPM_CLI_VERSION_OUTPUT=codex-cli %FAKE_NPM_INSTALLED_VERSION%"

if defined FAKE_NPM_ARGUMENT_LOG >> "%FAKE_NPM_ARGUMENT_LOG%" echo COMMAND=%*
if defined FAKE_NPM_ENVIRONMENT_LOG (
  >> "%FAKE_NPM_ENVIRONMENT_LOG%" echo COMMAND=%~1
  >> "%FAKE_NPM_ENVIRONMENT_LOG%" echo NPM_CONFIG_REGISTRY=%NPM_CONFIG_REGISTRY%
  >> "%FAKE_NPM_ENVIRONMENT_LOG%" echo NPM_CONFIG_USERCONFIG=%NPM_CONFIG_USERCONFIG%
  >> "%FAKE_NPM_ENVIRONMENT_LOG%" echo NPM_CONFIG_GLOBALCONFIG=%NPM_CONFIG_GLOBALCONFIG%
  >> "%FAKE_NPM_ENVIRONMENT_LOG%" echo NPM_CONFIG_ATTACKER=%NPM_CONFIG_ATTACKER%
  >> "%FAKE_NPM_ENVIRONMENT_LOG%" echo NPM_TOKEN=%NPM_TOKEN%
  >> "%FAKE_NPM_ENVIRONMENT_LOG%" echo NODE_AUTH_TOKEN=%NODE_AUTH_TOKEN%
)

if /I "%~1"=="view" goto view
if /I "%~1"=="install" goto install

>&2 echo fake-npm: unsupported command %~1
exit /b 64

:view
if /I "%FAKE_NPM_FAIL_COMMAND%"=="view" exit /b 41
if /I "%FAKE_NPM_METADATA_CASE%"=="malformed" echo {"metadata-super-secret":
if /I "%FAKE_NPM_METADATA_CASE%"=="malformed" exit /b 0
if /I "%FAKE_NPM_METADATA_CASE%"=="array" echo [{"version":"%FAKE_NPM_VERSION%","dist.integrity":"%FAKE_NPM_INTEGRITY%"}]
if /I "%FAKE_NPM_METADATA_CASE%"=="array" exit /b 0
if /I "%FAKE_NPM_METADATA_CASE%"=="missing-field" echo {"version":"%FAKE_NPM_VERSION%"}
if /I "%FAKE_NPM_METADATA_CASE%"=="missing-field" exit /b 0
if /I "%FAKE_NPM_METADATA_CASE%"=="wrong-type" echo {"version":123,"dist.integrity":["invalid"]}
if /I "%FAKE_NPM_METADATA_CASE%"=="wrong-type" exit /b 0
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
if /I "%FAKE_NPM_PACKAGE_CASE%"=="malformed" > "%FAKE_NPM_PREFIX%\node_modules\@openai\codex\package.json" echo {"package-super-secret":
if /I "%FAKE_NPM_PACKAGE_CASE%"=="wrong-type" > "%FAKE_NPM_PREFIX%\node_modules\@openai\codex\package.json" echo {"name":"@openai/codex","version":123}
if not defined FAKE_NPM_PACKAGE_CASE > "%FAKE_NPM_PREFIX%\node_modules\@openai\codex\package.json" echo {"name":"@openai/codex","version":"%FAKE_NPM_INSTALLED_VERSION%"}
> "%FAKE_NPM_PREFIX%\node_modules\@openai\codex\bin\codex.js" echo fake-codex-cli
if /I "%FAKE_NPM_LOCK_CASE%"=="malformed" > "%FAKE_NPM_PREFIX%\package-lock.json" echo {"lock-super-secret":
if /I "%FAKE_NPM_LOCK_CASE%"=="missing-entry" > "%FAKE_NPM_PREFIX%\package-lock.json" echo {"lockfileVersion":3,"packages":{}}
if /I "%FAKE_NPM_LOCK_CASE%"=="wrong-type" > "%FAKE_NPM_PREFIX%\package-lock.json" echo {"lockfileVersion":3,"packages":{"node_modules/@openai/codex":"invalid"}}
if not defined FAKE_NPM_LOCK_CASE > "%FAKE_NPM_PREFIX%\package-lock.json" echo {"lockfileVersion":3,"packages":{"node_modules/@openai/codex":{"name":"@openai/codex","version":"%FAKE_NPM_INSTALLED_VERSION%","integrity":"%FAKE_NPM_INSTALLED_INTEGRITY%"}}}
if /I "%FAKE_NPM_SKIP_CLI%"=="1" exit /b 0
> "%FAKE_NPM_PREFIX%\node_modules\.bin\codex.cmd" echo @echo off
if /I not "%FAKE_NPM_CLI_EMPTY%"=="1" >> "%FAKE_NPM_PREFIX%\node_modules\.bin\codex.cmd" echo echo %FAKE_NPM_CLI_VERSION_OUTPUT%
if defined FAKE_NPM_CLI_SECOND_LINE >> "%FAKE_NPM_PREFIX%\node_modules\.bin\codex.cmd" echo echo %FAKE_NPM_CLI_SECOND_LINE%
if defined FAKE_NPM_CLI_STDERR >> "%FAKE_NPM_PREFIX%\node_modules\.bin\codex.cmd" echo ^>^&2 echo %FAKE_NPM_CLI_STDERR%
if defined FAKE_NPM_CLI_EXIT_CODE >> "%FAKE_NPM_PREFIX%\node_modules\.bin\codex.cmd" echo exit /b %FAKE_NPM_CLI_EXIT_CODE%
exit /b 0
