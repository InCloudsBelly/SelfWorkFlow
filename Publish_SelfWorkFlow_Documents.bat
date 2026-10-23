@echo off
setlocal
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo SelfWorkflow maintainer Python environment is missing. Consumers read SKILL.md directly.
  exit /b 2
)
"%~dp0.venv\Scripts\python.exe" -m selfworkflow.cli skill sync --repository "%~dp0." %*
exit /b %errorlevel%
