@echo off
rem Começa um histórico de códigos novo. O atual fica guardado em historico_antigo\.
cd /d "%~dp0"
".venv\Scripts\python.exe" colador.py --limpar-historico
pause
