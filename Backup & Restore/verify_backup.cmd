@echo off
setlocal
if "%~1"=="" (
  echo Usage: verify_backup.cmd "E:\path\to\charity-prod-db-YYYYMMDD_HHMMSS.tar.gz"
  exit /b 1
)
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0verify_backup.ps1" -BackupArchivePath "%~1"
exit /b %ERRORLEVEL%
