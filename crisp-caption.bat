@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ============================================
echo   crisp-caption 主控台
echo ============================================
echo.

rem ---- 首次執行嚮導 ----
if not exist ".venv\Scripts\python.exe" (
  echo [首次] 尚未建立 .venv。需要完整安裝（Python 3.11+）。
  echo.
  set "CHOICE="
  set /p CHOICE=是否現在完整安裝？[y/N]: 
  if /I "!CHOICE!"=="y" goto setup
)

:menu
echo 請選擇操作：
echo.
echo   [1] 全新安裝（建 .venv + 裝依賴）
echo   [2] 下載 CrispASR / llama.cpp / 模型
echo   [3] 檢查依賴
echo   [4] 啟動（本機 / Colab / 診斷）
echo   [0] 退出
echo.
set "OP="
set /p OP=選擇: 

if "%OP%"=="1" goto setup
if "%OP%"=="2" goto download
if "%OP%"=="3" goto check
if "%OP%"=="4" goto run_menu
if "%OP%"=="0" exit /b 0
echo 無效選擇。 & echo. & goto menu

:setup
echo == 完整安裝 ==
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
echo 依賴安裝完成。接下來下載 CrispASR/llama/模型。
pause
goto download

:download
echo.
echo 下載項目：
echo   [1] CrispASR
echo   [2] llama.cpp
echo   [3] 模型
echo   [4] 全部
echo   [0] 返回
echo.
set "OP="
set /p OP=選擇: 
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
echo 啟動模式：
echo   [1] 本機模式（本機 CrispASR + 本機翻譯）
echo   [2] Colab 遠端（用 WebUI Connect 設定）
echo   [3] 診斷模式（-v）
echo   [0] 返回
echo.
set "OP="
set /p OP=選擇: 
if "%OP%"=="1" goto run_local
if "%OP%"=="2" goto run_colab
if "%OP%"=="3" goto run_diag
if "%OP%"=="0" goto menu
echo 無效選擇。 & echo. & goto run_menu

:run_local
echo == 本機模式 ==
call scripts\start-translation-server-windows.bat
start "" http://127.0.0.1:8765/
call scripts\_run_py.bat bridge_server.py
pause
goto menu

:run_colab
echo == Colab 遠端 ==
echo 開瀏覽器，用 Connect 設定 Colab URL/key。
start "" http://127.0.0.1:8765/
call scripts\_run_py.bat bridge_server.py
pause
goto menu

:run_diag
echo == 診斷模式 ==
call scripts\_run_py.bat bridge_server.py -v
pause
goto menu
