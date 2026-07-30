@echo off
setlocal
cd /d "%~dp0\.."

set "FORCE="
set "BACKEND=auto"
:parse
if "%~1"=="" goto run
if /I "%~1"=="--force" set "FORCE=--force"
if /I "%~1"=="--cuda" set "BACKEND=cuda"
if /I "%~1"=="--vulkan" set "BACKEND=vulkan"
if /I "%~1"=="--backend" (
  set "BACKEND=%~2"
  shift
)
shift
goto parse

:run
echo Installing CrispASR for Windows (backend=%BACKEND%; CUDA preferred when available)...
call scripts\_run_py.bat scripts\download_file.py install-crispasr-windows --backend %BACKEND% %FORCE%
if errorlevel 1 (
  echo [FAIL] CrispASR download failed.
  pause
  exit /b 1
)

if not exist "tools\crispasr\crispasr.exe" (
  echo [FAIL] crispasr.exe was not found: tools\crispasr\crispasr.exe
  pause
  exit /b 1
)

if exist "tools\crispasr\.backend" (
  set /p BACKEND_USED=<tools\crispasr\.backend
  echo [OK] CrispASR backend: %BACKEND_USED%
)
"tools\crispasr\crispasr.exe" --version
echo [OK] CrispASR installed at tools\crispasr
pause
