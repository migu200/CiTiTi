@echo off
rem Mostra o ecrã do BlueStacks numa janela normal (visível pelo acesso remoto).
rem Usa o mesmo ADB do colador, para não interromper o programa.
cd /d "%~dp0"
set ADB=%~dp0platform-tools\adb.exe
"%ADB%" connect 127.0.0.1:5555 >nul
start "" scrcpy\scrcpy.exe -s 127.0.0.1:5555 --no-audio --window-title "MobiCTT (BlueStacks)"
