@echo off
rem Compatibility shortcut. SCHT now uses the single-file build as its standard release format.
call "%~dp0build_exe.bat"
exit /b %errorlevel%
