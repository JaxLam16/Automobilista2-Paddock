@echo off
REM Double-click before joining the lobby. Leave it running; Ctrl+C or close the window when done.
REM First run on a PC installs the Python libraries automatically.
cd /d "%~dp0"

REM Find Python: "python" first, then the "py" launcher
set "PY=python"
%PY% --version >nul 2>nul || set "PY=py -3"
%PY% --version >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Install Python 3.10+ from python.org and tick "Add python.exe to PATH".
    pause
    exit /b 1
)

REM Install dependencies into this same Python if they're missing
%PY% -c "import numpy, pandas, pyarrow, PIL" >nul 2>nul
if errorlevel 1 (
    echo Installing numpy, pandas, pyarrow - first run only, takes a minute...
    %PY% -m pip install -e .
    if errorlevel 1 (
        echo.
        echo Install failed - see the error above.
        pause
        exit /b 1
    )
)

%PY% -m ams2season record --out recordings --label %USERNAME%
pause
