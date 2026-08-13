@echo off
setlocal
cd /d "%~dp0\.."

echo Downloading models listed in models\manifest.json...
call scripts\_run_py.bat scripts\download_file.py manifest --manifest models\manifest.json
if errorlevel 1 (
  echo [FAIL] Model download failed.
  pause
  exit /b 1
)

echo [OK] Models downloaded.
pause
