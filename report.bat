@echo off
REM Double-click after a race: builds the visual report for your newest race and opens it in your browser.
REM Drag a race folder onto this file to report that race instead.
cd /d "%~dp0"
set "PY=python"
%PY% --version >nul 2>nul || set "PY=py -3"
if "%~1"=="" (
    %PY% -m ams2season report
) else (
    %PY% -m ams2season report "%~1"
)
if errorlevel 1 pause
