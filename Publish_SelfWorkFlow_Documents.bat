@echo off
setlocal
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo SelfWorkflow maintainer Python environment is missing. Consumers only read public\WORKFLOW.md.
  exit /b 2
)
"%~dp0.venv\Scripts\python.exe" -m selfworkflow.cli documents publish --repository "%~dp0." --output "%~dp0public" %*
exit /b %errorlevel%
