@echo off
rem Screenwall for Windows (experimental). Double-click to start; this window stays open while
rem the app runs, and closing it (or Ctrl+C) stops the server. All the work is in launcher.ps1.
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launcher.ps1"
set "SW_EXIT=%ERRORLEVEL%"
rem Keep an error readable when started by double-click; CI (CI=true) must not wait for a key.
if not "%SW_EXIT%"=="0" if not defined CI pause
exit /b %SW_EXIT%
