@echo off
setlocal
cd /d "%~dp0\.."

echo === crisp-caption Colab connection setup ===
echo.
echo 1) In Colab, copy the TOKEN line (CRISPASR_REMOTE_KEY=...)
echo 2) In Colab, copy the URL line (TUNNEL=https://...trycloudflare.com)
echo.
echo Paste them below when prompted.
echo.

set /p CRISPASR_REMOTE_KEY=Step 1 - Paste the TOKEN: 
set /p TUNNEL=Step 2 - Paste the Cloudflare URL: 

if "%CRISPASR_REMOTE_KEY%"=="" (
  echo [FAIL] No token provided.
  pause
  exit /b 1
)
if "%TUNNEL%"=="" (
  echo [FAIL] No Cloudflare URL provided.
  pause
  exit /b 1
)

echo.
echo Confirming your input:
echo   Token: %CRISPASR_REMOTE_KEY%
echo   URL:   %TUNNEL%
echo.

set OPENAI_API_KEY=%CRISPASR_REMOTE_KEY%

if exist "profiles\profile.ja.json" (
  copy /Y "profiles\profile.ja.json" "profiles\profile.ja.json.bak" >nul
)
copy /Y "profiles\profile.ja.colab.example.json" "profiles\profile.ja.json" >nul

set "HOST=%TUNNEL:http://=%"
set "HOST=%HOST:https://=%"
set "HOST=%HOST:/=%"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$p='profiles\profile.ja.json'; $j=Get-Content $p -Raw | ConvertFrom-Json; $j | Add-Member -NotePropertyName 'remote_asr_url' -NotePropertyValue 'wss://%HOST%/asr/stream' -Force; $j | Add-Member -NotePropertyName 'translate_url' -NotePropertyValue 'https://%HOST%/v1/chat/completions' -Force; $j | ConvertTo-Json -Depth 10 | Set-Content $p -Encoding UTF8"

echo.
echo [OK] profile updated. Connected to %HOST%
echo Starting crisp-caption...
call scripts\run-windows.bat
