@echo off
setlocal
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0backup_production.ps1" %*
exit /b %ERRORLEVEL%
