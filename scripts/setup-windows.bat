@echo off
setlocal
cd /d "%~dp0\.."

echo === crisp-caption Windows setup ===

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
    echo [FAIL] Python was not found on PATH.
    echo Install Python 3.11+ from https://www.python.org/downloads/windows/
    pause
    exit /b 1
  )
  set "PYLAUNCHER=python"
)

%PYLAUNCHER% --version
if errorlevel 1 (
  echo [FAIL] Python exists but could not run.
  pause
  exit /b 1
)

%PYLAUNCHER% -m pip --version >nul 2>nul
if errorlevel 1 (
  echo [FAIL] pip was not found for this Python.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating .venv...
  %PYLAUNCHER% -m venv .venv
  if errorlevel 1 (
    echo [FAIL] Failed to create .venv.
    pause
    exit /b 1
  )
)

set "PY=%CD%\.venv\Scripts\python.exe"

"%PY%" --version >nul 2>nul
if errorlevel 1 (
  echo [FAIL] The virtual environment Python could not start: %PY%
  echo Delete .venv and rerun setup after installing a working Python 3.11+.
  pause
  exit /b 1
)

echo Upgrading pip...
"%PY%" -m pip install --upgrade pip
if errorlevel 1 goto fail

echo Installing Python dependencies...
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 goto fail

echo Installing overlay dependencies...
"%PY%" -m pip install -r requirements-overlay.txt
if errorlevel 1 goto fail

if not exist "profiles\profile.ja.json" (
  echo Creating local profile profiles\profile.ja.json...
  copy /Y "profiles\profile.ja.example.json" "profiles\profile.ja.json" >nul
)

echo.
echo [OK] Setup completed. Browser UI is static\index.html (no Node build).
echo Next steps:
echo   scripts\download-crispasr-windows.bat
echo   scripts\download-llama-cpp-windows.bat
echo   scripts\models-download.bat
echo   scripts\check-deps.bat
pause
exit /b 0

:fail
echo [FAIL] Setup failed.
pause
exit /b 1
