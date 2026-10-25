@echo off
rem Launch PlaylistHelper from source without leaving a console window open.
rem Installs any missing packages on first run.
cd /d "%~dp0"
set "PY=python"
where python >nul 2>nul || set "PY=py"
%PY% -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>nul || goto :nopython
%PY% -c "import PySide6, requests, ytmusicapi, pyrekordbox" >nul 2>nul || (
    echo Installing required packages...
    %PY% -m pip install -r requirements.txt || goto :failed
)
start "" %PY%w "%~dp0playlist_helper.py"
exit /b 0

:nopython
echo Python 3.9 or newer was not found.
echo Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH"),
echo or use the ready-made PlaylistHelper.exe instead.
pause
exit /b 1

:failed
echo.
echo Installing packages failed. See the messages above.
pause
exit /b 1
