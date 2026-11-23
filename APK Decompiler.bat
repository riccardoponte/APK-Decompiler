@echo off
rem Avvia APK Decompiler con il Python portatile incluso nella cartella "runtime".
rem Puoi anche trascinare un file .apk su questo .bat.
cd /d "%~dp0"
if not exist "runtime\pythonw.exe" (
    echo Runtime Python non trovato nella cartella "runtime".
    pause
    exit /b 1
)
start "" "runtime\pythonw.exe" -s -E main.py %*
