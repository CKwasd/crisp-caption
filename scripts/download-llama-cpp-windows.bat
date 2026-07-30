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
echo Installing llama.cpp for Windows (backend=%BACKEND%; CUDA preferred when available)...
call scripts\_run_py.bat scripts\download_file.py install-llama-windows --backend %BACKEND% %FORCE%
if errorlevel 1 (
  echo [FAIL] llama.cpp download failed.
  pause
  exit /b 1
)

if not exist "tools\llama.cpp\llama-server.exe" (
  echo [FAIL] llama-server.exe was not found: tools\llama.cpp\llama-server.exe
  pause
  exit /b 1
)

if exist "tools\llama.cpp\.backend" (
  set /p BACKEND_USED=<tools\llama.cpp\.backend
  echo [OK] llama.cpp backend: %BACKEND_USED%
)
"tools\llama.cpp\llama-server.exe" --help >nul
echo [OK] llama.cpp installed at tools\llama.cpp
pause
