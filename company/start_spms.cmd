@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo SPMS venv not found. Stop and check the installation folder.
  pause
  exit /b 1
)
echo SPMS uses the ORIGINAL database. Stop all other SPMS servers first.
echo Default: all reachable IPv4 sources may read SPMS. Use --restrict-sources for the approved subnet allowlist.
".venv\Scripts\python.exe" ".\company\production_server.py" %*
set "SPMS_RESULT=%ERRORLEVEL%"
echo.
echo SPMS stopped. Keep any error messages for diagnosis.
pause
exit /b %SPMS_RESULT%
