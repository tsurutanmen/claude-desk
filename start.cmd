@echo off
rem Claude Desk: the voice engine, the wallpaper server and the "Hey Claude" listener
rem VOICEVOX: put the path of its run.exe in voicevox.path beside this file (optional)
set VOICEVOX=
if exist "%~dp0voicevox.path" set /p VOICEVOX=<"%~dp0voicevox.path"
if defined VOICEVOX start "VOICEVOX engine" /min "%VOICEVOX%" --host 127.0.0.1 --port 50021
start "Claude Desk server" /min "%~dp0venv\Scripts\python.exe" "%~dp0server.py"
start "Claude Desk listener" "%~dp0venv\Scripts\python.exe" "%~dp0wake.py"
