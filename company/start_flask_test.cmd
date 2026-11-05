@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo SPMS venv not found. Stop and check the installation folder.
  pause
  exit /b 1
)
echo Stop the original SPMS server before running this comparison test.
echo Test edits use a new database copy and are NOT saved to production.
".venv\Scripts\python.exe" ".\company\flask_server.py" %*
set "SPMS_RESULT=%ERRORLEVEL%"
echo.
echo Test server stopped. Keep any error messages for diagnosis.
pause
exit /b %SPMS_RESULT%
