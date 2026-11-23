@echo off
rem Avvia APK Decompiler mostrando la console (utile per vedere eventuali errori).
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
"runtime\python.exe" -s -E main.py %*
pause
