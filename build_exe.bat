@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "VENV=.venv-build"
set "PYTHON_CMD="
set "SCHT_VERSION="
set "PAUSE_ON_EXIT=1"
if /I "%~1"=="--no-pause" set "PAUSE_ON_EXIT=0"

rem Prefer the Windows Python launcher, but also support a normal python.exe.
where py >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD (
  where python >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
  echo ERROR: Python 3 was not found.
  echo Install current 64-bit Python from python.org and enable Add Python to PATH.
  goto error
)

rem Read: APP_VERSION = "x.y.z". %%~V removes the surrounding quotes.
for /f "tokens=3" %%V in ('findstr /B /C:"APP_VERSION = " "sc_hauling_tracker.py"') do set "SCHT_VERSION=%%~V"
if not defined SCHT_VERSION set "SCHT_VERSION=unknown"

echo ============================================================
echo  SCHT v%SCHT_VERSION% - Portable Single-EXE Builder
echo ============================================================
echo.
echo Source folder:
echo   %CD%
echo Output:
echo   %CD%\dist\SCHT.exe
echo.

echo [1/6] Preparing isolated build environment...
if not exist "%VENV%\Scripts\python.exe" (
  %PYTHON_CMD% -m venv "%VENV%"
  if errorlevel 1 goto error
)

set "VENV_PYTHON=%CD%\%VENV%\Scripts\python.exe"
if not exist "%VENV_PYTHON%" (
  echo ERROR: The build environment is incomplete.
  echo Delete the .venv-build folder and run this file again.
  goto error
)

set PYTHONUTF8=1
set PIP_DISABLE_PIP_VERSION_CHECK=1

echo [2/6] Updating build tools...
"%VENV_PYTHON%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto error

echo [3/6] Installing desktop and packaging dependencies...
"%VENV_PYTHON%" -m pip install -r requirements-build.txt
if errorlevel 1 goto error

echo [4/6] Running regression tests...
"%VENV_PYTHON%" -m unittest discover -s tests -p "test_*.py"
if errorlevel 1 goto error

echo [5/6] Cleaning previous build output...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist __pycache__ rmdir /s /q __pycache__

if exist dist (
  echo ERROR: The dist folder could not be removed.
  echo Close every running SCHT.exe and any File Explorer preview using it, then retry.
  goto error
)
if exist build (
  echo ERROR: The build folder could not be removed.
  goto error
)

echo [6/6] Building SCHT.exe...
"%VENV_PYTHON%" -m PyInstaller --noconfirm --clean SCHT.spec
if errorlevel 1 goto error

if not exist "dist\SCHT.exe" (
  echo ERROR: PyInstaller finished without creating dist\SCHT.exe.
  goto error
)

echo.
echo Build complete:
echo   %CD%\dist\SCHT.exe
echo.
echo Before testing, close every older SCHT window and run this exact file.
echo The app header must show v%SCHT_VERSION%.
echo.
if "%PAUSE_ON_EXIT%"=="1" pause
exit /b 0

:error
echo.
echo Build failed. Review the first ERROR line above.
echo Common fixes:
echo - Extract the ZIP before building.
echo - Close any running SCHT.exe before rebuilding.
echo - Delete .venv-build if its Python installation was moved or removed.
echo - Install current 64-bit Python from python.org.
echo - Temporarily allow Python and PyInstaller through antivirus protection.
echo - Install or repair Microsoft Edge WebView2 Runtime.
echo.
if "%PAUSE_ON_EXIT%"=="1" pause
exit /b 1
