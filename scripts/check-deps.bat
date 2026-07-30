@echo off
setlocal
cd /d "%~dp0\.."

call scripts\_run_py.bat scripts\check_deps.py
set "STATUS=%ERRORLEVEL%"
pause
exit /b %STATUS%
