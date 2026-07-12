@echo off
cd /d "%~dp0"
py -3 -c "import webview" >nul 2>nul
if errorlevel 1 (
  echo pywebview is not installed for this Python environment.
  echo Run build_exe.bat for the normal standalone application,
  echo or install requirements-build.txt for source development.
  pause
  exit /b 1
)
py -3 sc_hauling_tracker.py
if errorlevel 1 pause
