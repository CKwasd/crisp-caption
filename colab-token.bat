@echo off
set /p CRISPASR_REMOTE_TOKEN=Paste Colab token: 
set OPENAI_API_KEY=%CRISPASR_REMOTE_TOKEN%
call scripts\run-windows.bat
