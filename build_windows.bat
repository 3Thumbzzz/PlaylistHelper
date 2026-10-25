@echo off
rem Build dist\PlaylistHelper.exe. The Mac .dmg is built by GitHub Actions
rem (.github\workflows\build.yml) because it has to be made on a Mac.
cd /d "%~dp0"
python -m pip install --upgrade -r requirements.txt pyinstaller || goto :error
python build.py || goto :error
echo.
echo Done: %~dp0dist\PlaylistHelper.exe
pause
exit /b 0

:error
echo.
echo Build failed.
pause
exit /b 1
