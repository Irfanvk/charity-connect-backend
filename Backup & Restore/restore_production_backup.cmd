@echo off
setlocal
if "%~1"=="" (
  echo Usage: restore_production_backup.cmd "E:\path\to\charity-prod-db-YYYYMMDD_HHMMSS.tar.gz"
  exit /b 1
)
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0restore_production_backup.ps1" -BackupArchivePath "%~1"
exit /b %ERRORLEVEL%
