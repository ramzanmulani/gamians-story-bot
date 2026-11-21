@echo off
REM  Copy the long token first (Ctrl+C), then double-click this file.
REM  It saves the clipboard into token.txt and runs the setup.
setlocal
cd /d "%~dp0"
echo.
echo   Gamians Story Bot - save token and set up
echo   ==========================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$t = (Get-Clipboard -Raw) -replace '\s',''; if ($t.Length -lt 100) { Write-Host '  The clipboard does not hold a token. Copy the long token first (Ctrl+C), then run this again.' -ForegroundColor Red; exit 1 }; [IO.File]::WriteAllText((Join-Path '%~dp0' 'token.txt'), $t); Write-Host ('  Token saved (' + $t.Length + ' characters).') -ForegroundColor Green"
if errorlevel 1 goto end
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
:end
echo.
echo   ------------------------------------------------------------
echo   Window stays open so you can read the result. Press a key to close.
pause >nul
endlocal
