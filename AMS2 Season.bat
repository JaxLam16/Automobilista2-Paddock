@echo off
REM Opens the AMS2 Season app. First run installs what it needs; after that, use
REM Settings > Create desktop shortcut and you won't need this file again.
cd /d "%~dp0"
set "PY=python"
set "PYW=pythonw"
%PY% --version >nul 2>nul || (set "PY=py -3" & set "PYW=pyw -3")
%PY% --version >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Install Python 3.10+ from python.org and tick "Add python.exe to PATH".
    pause
    exit /b 1
)
%PY% -c "import numpy, pandas, pyarrow, PIL" >nul 2>nul
if errorlevel 1 (
    echo Installing numpy, pandas, pyarrow - first run only, takes a minute...
    %PY% -m pip install -e .
    if errorlevel 1 (
        echo Install failed - see the error above.
        pause
        exit /b 1
    )
)
start "" %PYW% -m ams2season app
