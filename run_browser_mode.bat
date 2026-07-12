@echo off
cd /d "%~dp0"
echo Diagnostic browser mode - native overlay is unavailable.
py -3 sc_hauling_tracker.py --browser
pause
