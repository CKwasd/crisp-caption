@echo off
setlocal
cd /d "%~dp0\.."

if exist "profiles\profile.ja.json" (
  copy /Y "profiles\profile.ja.json" "profiles\profile.ja.json.bak" >nul
)
copy /Y "profiles\profile.ja.colab.example.json" "profiles\profile.ja.json" >nul

set /p CRISPASR_REMOTE_TOKEN=Paste Colab token: 
set /p TUNNEL=Paste Cloudflare URL (e.g. https://xxx.trycloudflare.com): 
set OPENAI_API_KEY=%CRISPASR_REMOTE_TOKEN%

set "HOST=%TUNNEL:http://=%"
set "HOST=%HOST:https://=%"
set "HOST=%HOST:/=%"

powershell -NoProfile -Command "$p='profiles\profile.ja.json'; $j=Get-Content $p -Raw | ConvertFrom-Json; $j | Add-Member -NotePropertyName 'remote_asr_url' -NotePropertyValue 'wss://%HOST%/asr/stream' -Force; $j | Add-Member -NotePropertyName 'translate_url' -NotePropertyValue 'https://%HOST%/v1/chat/completions' -Force; $j | ConvertTo-Json -Depth 10 | Set-Content $p -Encoding UTF8"

echo [OK] profile updated. Starting crisp-caption...
call scripts\run-windows.bat
