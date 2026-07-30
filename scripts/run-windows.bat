@echo off
setlocal
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
  echo [FAIL] .venv not found. Run scripts\setup-windows.bat first.
  pause
  exit /b 1
)

if exist "tools\llama.cpp\llama-server.exe" (
  if exist "models\translation\Hy-MT2-1.8B-Q4_K_M.gguf" (
    call scripts\_run_py.bat -c "import urllib.request as u; exit(0 if u.urlopen('http://127.0.0.1:8080/health',timeout=2).status<400 else 1)" 2>nul
    if errorlevel 1 (
      echo Starting translation server in a new window...
      start "crisp-caption translation" cmd /k scripts\start-translation-server-windows.bat
    )
  )
)

echo.
echo Select a profile at http://127.0.0.1:8765/ to start capture.
echo.
start "" powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process 'http://127.0.0.1:8765/'"
call scripts\_run_py.bat bridge_server.py
pause
