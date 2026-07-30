@echo off
setlocal
set "PY=%CD%\.venv\Scripts\python.exe"
if exist "%PY%" goto run_venv
py -3 %*
if not errorlevel 1 exit /b 0
python %*
exit /b %ERRORLEVEL%

:run_venv
"%PY%" %*
exit /b %ERRORLEVEL%
