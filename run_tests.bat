@echo off
setlocal
cd /d "%~dp0"

if exist ".venv-build\Scripts\python.exe" (
  ".venv-build\Scripts\python.exe" -m unittest discover -s tests
) else (
  py -3 -m unittest discover -s tests
)
