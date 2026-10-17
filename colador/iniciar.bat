@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" colador.py %*
pause
