@echo off
REM Copy the Threads token first (Ctrl+C), then double-click this.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0save_secret.ps1" -Kind threads
pause
