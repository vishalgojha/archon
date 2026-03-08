@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "ARCHON_INSTALL_VIA_CMD=1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%install.ps1" %*
exit /b %errorlevel%
