@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "SCHT_VERSION="
set "ISCC_EXE="

for /f "tokens=3" %%V in ('findstr /B /C:"APP_VERSION = " "sc_hauling_tracker.py"') do set "SCHT_VERSION=%%~V"
if not defined SCHT_VERSION set "SCHT_VERSION=unknown"

if not exist "dist\SCHT.exe" (
  echo SCHT.exe is missing. Building the standalone executable first...
  call build_exe.bat --no-pause
  if errorlevel 1 goto error
)

where ISCC.exe >nul 2>nul
if not errorlevel 1 set "ISCC_EXE=ISCC.exe"
if not defined ISCC_EXE if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC_EXE=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC_EXE if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC_EXE=%ProgramFiles%\Inno Setup 6\ISCC.exe"

if not defined ISCC_EXE (
  echo ERROR: Inno Setup 6 was not found.
  echo Install Inno Setup 6 on this build PC, then run build_installer.bat again.
  goto error
)

if exist "dist\SCHT-Setup-%SCHT_VERSION%.exe" del /q "dist\SCHT-Setup-%SCHT_VERSION%.exe"

echo ============================================================
echo  SCHT v%SCHT_VERSION% - Windows Installer Builder
echo ============================================================
echo.
echo Input:
echo   %CD%\dist\SCHT.exe
echo Output:
echo   %CD%\dist\SCHT-Setup-%SCHT_VERSION%.exe
echo.

"%ISCC_EXE%" /DMyAppVersion=%SCHT_VERSION% "installer\SCHT.iss"
if errorlevel 1 goto error

if not exist "dist\SCHT-Setup-%SCHT_VERSION%.exe" (
  echo ERROR: Inno Setup finished without creating the installer.
  goto error
)

echo.
echo Installer build complete:
echo   %CD%\dist\SCHT-Setup-%SCHT_VERSION%.exe
echo.
echo Test install, launch, and uninstall on a clean Windows user account before release.
pause
exit /b 0

:error
echo.
echo Installer build failed. Review the first ERROR line above.
pause
exit /b 1
