@echo off
setlocal
cd /d "%~dp0\.."

set "LLAMA_SERVER=tools\llama.cpp\llama-server.exe"
set "MODEL=models\translation\Hy-MT2-1.8B-Q4_K_M.gguf"
set "BACKEND=vulkan"
if exist "tools\llama.cpp\.backend" set /p BACKEND=<tools\llama.cpp\.backend

if /I "%LOW_VRAM%"=="1" (
  set "CTX=4096"
  set "BATCH=512"
  set "UBATCH=256"
) else (
  set "CTX=8192"
  set "BATCH=2048"
  set "UBATCH=1024"
)

if not exist "%LLAMA_SERVER%" (
  echo [FAIL] llama-server not found: %LLAMA_SERVER%
  echo Run scripts\download-llama-cpp-windows.bat first.
  pause
  exit /b 1
)

if not exist "%MODEL%" (
  echo [FAIL] translation model not found: %MODEL%
  echo Run scripts\models-download.bat first.
  pause
  exit /b 1
)

echo Starting llama-server backend=%BACKEND% (CTX=%CTX%, BATCH=%BATCH%) ...
if /I "%BACKEND%"=="cuda" (
  "%LLAMA_SERVER%" ^
    -m "%MODEL%" ^
    -a Hy-MT2-1.8B ^
    -ngl all ^
    -sm none ^
    -c %CTX% ^
    -b %BATCH% ^
    -ub %UBATCH% ^
    -fa on ^
    -np 1 ^
    --cache-prompt ^
    --cache-reuse 64 ^
    --host 127.0.0.1 ^
    --port 8080
) else (
  "%LLAMA_SERVER%" ^
    -m "%MODEL%" ^
    -a Hy-MT2-1.8B ^
    -dev Vulkan0 ^
    -ngl all ^
    -sm none ^
    -c %CTX% ^
    -b %BATCH% ^
    -ub %UBATCH% ^
    -fa on ^
    -np 1 ^
    --cache-prompt ^
    --cache-reuse 64 ^
    --host 127.0.0.1 ^
    --port 8080
)

pause
