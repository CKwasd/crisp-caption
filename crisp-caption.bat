@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ============================================
echo   crisp-caption console
echo ============================================
echo.

rem ---- first-run wizard ----
if not exist ".venv\Scripts\python.exe" (
  echo [first-run] .venv not found. Full setup needs Python 3.11+.
  echo.
  set "CHOICE="
  set /p CHOICE=Run full setup now? [y/N]: 
  if /I "!CHOICE!"=="y" goto setup
)

:menu
echo Choose action:
echo.
echo   [1] Full setup (create .venv + install deps)
echo   [2] Download CrispASR / llama.cpp / models
echo   [3] Check dependencies
echo   [4] Start (Local / Colab / Diagnostics)
echo   [0] Exit
echo.
set "OP="
set /p OP=Choice: 

if "%OP%"=="1" goto setup
if "%OP%"=="2" goto download
if "%OP%"=="3" goto check
if "%OP%"=="4" goto run_menu
if "%OP%"=="0" exit /b 0
echo Invalid choice. & echo. & goto menu

:setup
echo == Full setup ==
set "PYLAUNCHER="
where py >nul 2>nul
if not errorlevel 1 set "PYLAUNCHER=py -3"
if not "%PYLAUNCHER%"=="" (
  %PYLAUNCHER% --version >nul 2>nul
  if errorlevel 1 set "PYLAUNCHER="
)
if "%PYLAUNCHER%"=="" (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [FAIL] Python not found. Install Python 3.11+.
    pause
    exit /b 1
  )
  set "PYLAUNCHER=python"
)
if not exist ".venv\Scripts\python.exe" (
  echo Creating .venv...
  %PYLAUNCHER% -m venv .venv
  if errorlevel 1 ( echo [FAIL] venv create failed. & pause & exit /b 1 )
)
set "PY=%CD%\.venv\Scripts\python.exe"
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 ( echo [FAIL] deps install failed. & pause & goto menu )
"%PY%" -m pip install -r requirements-overlay.txt
echo.
echo Dependencies installed. Next download CrispASR / llama.cpp / models.
pause
goto download

:download
echo.
echo Download:
echo   [1] CrispASR
echo   [2] llama.cpp
echo   [3] Models
echo   [4] All
echo   [0] Back
echo.
set "OP="
set /p OP=Choice: 
if "%OP%"=="1" call scripts\_run_py.bat scripts\download_file.py install-crispasr-windows
if "%OP%"=="2" call scripts\_run_py.bat scripts\download_file.py install-llama-windows
if "%OP%"=="3" call scripts\_run_py.bat scripts\download_file.py manifest --manifest models\manifest.json
if "%OP%"=="4" (
  call scripts\_run_py.bat scripts\download_file.py install-crispasr-windows
  call scripts\_run_py.bat scripts\download_file.py install-llama-windows
  call scripts\_run_py.bat scripts\download_file.py manifest --manifest models\manifest.json
)
if "%OP%"=="0" goto menu
pause
goto menu

:check
call scripts\_run_py.bat scripts\check_deps.py
pause
goto menu

:run_menu
echo.
echo Start mode:
echo   [1] Local (local CrispASR + local translation)
echo   [2] Colab (fill URL/key via Web UI Connect)
echo   [3] Diagnostics (-v)
echo   [0] Back
echo.
set "OP="
set /p OP=Choice: 
if "%OP%"=="1" goto run_local
if "%OP%"=="2" goto run_colab
if "%OP%"=="3" goto run_diag
if "%OP%"=="0" goto menu
echo Invalid choice. & echo. & goto run_menu

:run_local
echo == Local mode ==
if not exist ".venv\Scripts\python.exe" (
  echo [FAIL] .venv not found. Run crisp-caption.bat menu 1 setup first.
  pause
  goto menu
)
set "LLAMA_SERVER=tools\llama.cpp\llama-server.exe"
set "MODEL=models\translation\Hy-MT2-1.8B-Q4_K_M.gguf"
set "BACKEND=vulkan"
if exist "tools\llama.cpp\.backend" set /p BACKEND=<tools\llama.cpp\.backend
set "CTX=8192"
set "BATCH=2048"
set "UBATCH=1024"
if /I "%LOW_VRAM%"=="1" (
  set "CTX=4096"
  set "BATCH=512"
  set "UBATCH=256"
)
if not exist "%LLAMA_SERVER%" (
  echo [FAIL] llama-server not found: %LLAMA_SERVER%. Download via menu 2.
  pause
  goto menu
)
if not exist "%MODEL%" (
  echo [FAIL] Translation model not found: %MODEL%. Download models via menu 2.
  pause
  goto menu
)
set "COMMON=-m %MODEL% -a Hy-MT2-1.8B -ngl all -sm none -c %CTX% -b %BATCH% -ub %UBATCH% -fa on -np 1 --cache-prompt --cache-reuse 64 --host 127.0.0.1 --port 8080"
if /I "%BACKEND%"=="cuda" (
  set "LLAMA_CMD=%LLAMA_SERVER% %COMMON%"
) else (
  set "LLAMA_CMD=%LLAMA_SERVER% -dev Vulkan0 %COMMON%"
)
echo Starting translation server in a new window (backend=%BACKEND%)...
start "crisp-caption translation" cmd /k "%LLAMA_CMD%"
start "" http://127.0.0.1:8765/
call scripts\_run_py.bat bridge_server.py
pause
goto menu

:run_colab
echo == Colab remote ==
echo Open browser, use Connect to set Colab URL / key.
start "" http://127.0.0.1:8765/
call scripts\_run_py.bat bridge_server.py
pause
goto menu

:run_diag
echo == Diagnostics ==
call scripts\_run_py.bat bridge_server.py -v
pause
goto menu
