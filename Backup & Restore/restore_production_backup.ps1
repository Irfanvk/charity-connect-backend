[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BackupArchivePath,
    [string]$ServerHost = "187.124.20.219",
    [string]$UserName = "root",
    [string]$RemoteProjectPath = "/root/charity-connect-backend",
    [string]$RemoteRestoreRoot = "/root/backups/charity-restore",
    [string]$ServiceName = "charity.service",
    [bool]$RestoreDatabase = $true,
    [bool]$RestoreGlobals = $false,
    [switch]$WhatIf
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Ensure-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found. Install OpenSSH client and ensure it is on PATH."
    }
}

Ensure-Command -Name "ssh"
Ensure-Command -Name "scp"

function Invoke-NativeChecked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [string]$ErrorMessage = "Native command failed"
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$ErrorMessage (exit code $LASTEXITCODE)"
    }
}

if (-not (Test-Path -Path $BackupArchivePath -PathType Leaf)) {
    throw "Backup archive not found: $BackupArchivePath"
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$archiveFileName = [System.IO.Path]::GetFileName($BackupArchivePath)
$remoteRestoreDir = "$RemoteRestoreRoot/$timestamp"
$remoteArchivePath = "$remoteRestoreDir/$archiveFileName"

$restoreDbFlag = if ($RestoreDatabase) { "1" } else { "0" }
$restoreGlobalsFlag = if ($RestoreGlobals) { "1" } else { "0" }

$remoteCommand = @'
set -e
mkdir -p '__REMOTE_RESTORE_DIR__/extracted'

if [ ! -f '__REMOTE_ARCHIVE_PATH__' ]; then
  echo 'Backup archive not found on remote host after upload.'
  exit 1
fi

tar -xzf '__REMOTE_ARCHIVE_PATH__' -C '__REMOTE_RESTORE_DIR__/extracted'

DUMP_PATH='__REMOTE_RESTORE_DIR__/extracted/charity_db.dump'
GLOBALS_PATH='__REMOTE_RESTORE_DIR__/extracted/charity_globals.sql'

if [ '__RESTORE_DB_FLAG__' = '1' ]; then
  if [ ! -f "$DUMP_PATH" ]; then
    echo 'Database dump not found in archive.'
    exit 1
  fi

  python3 - <<'PY'
import os
import subprocess
from urllib.parse import urlparse

env_path = '__REMOTE_PROJECT_PATH__/.env'
values = {}

if os.path.exists(env_path):
    with open(env_path, 'r', encoding='utf-8') as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, val = line.split('=', 1)
            val = val.strip()
            if len(val) >= 2 and ((val[0] == '"' and val[-1] == '"') or (val[0] == "'" and val[-1] == "'")):
                val = val[1:-1]
            values[key.strip()] = val

raw_db_url = values.get('DATABASE_URL') or os.getenv('DATABASE_URL')
if not raw_db_url:
    raise SystemExit('DATABASE_URL not found in remote environment. Restore aborted.')

parsed = urlparse(raw_db_url)
if parsed.scheme not in ('postgresql', 'postgres'):
    raise SystemExit(f'Unsupported database URL scheme: {parsed.scheme}')

host = parsed.hostname or '127.0.0.1'
port = parsed.port or 5432
user = parsed.username or 'postgres'
db_name = parsed.path.lstrip('/') or 'postgres'
password = parsed.password or ''

env = os.environ.copy()
env['PGPASSWORD'] = password
cmd = [
    'pg_restore',
    '--clean',
    '--if-exists',
    '--no-owner',
    '--no-privileges',
    '-h', host,
    '-p', str(port),
    '-U', user,
    '-d', db_name,
    '__DUMP_PATH__'
]
subprocess.run(cmd, check=True, env=env)
PY
fi

if [ '__RESTORE_GLOBALS_FLAG__' = '1' ]; then
  if [ ! -f "$GLOBALS_PATH" ]; then
    echo 'Globals SQL not found in archive.'
    exit 1
  fi

  python3 - <<'PY'
import os
import subprocess
from urllib.parse import urlparse

env_path = '__REMOTE_PROJECT_PATH__/.env'
values = {}

if os.path.exists(env_path):
    with open(env_path, 'r', encoding='utf-8') as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, val = line.split('=', 1)
            val = val.strip()
            if len(val) >= 2 and ((val[0] == '"' and val[-1] == '"') or (val[0] == "'" and val[-1] == "'")):
                val = val[1:-1]
            values[key.strip()] = val

raw_db_url = values.get('DATABASE_URL') or os.getenv('DATABASE_URL')
if not raw_db_url:
    raise SystemExit('DATABASE_URL not found in remote environment. Globals restore aborted.')

parsed = urlparse(raw_db_url)
if parsed.scheme not in ('postgresql', 'postgres'):
    raise SystemExit(f'Unsupported database URL scheme: {parsed.scheme}')

host = parsed.hostname or '127.0.0.1'
port = parsed.port or 5432
user = parsed.username or 'postgres'
password = parsed.password or ''

env = os.environ.copy()
env['PGPASSWORD'] = password
cmd = [
    'psql',
    '-h', host,
    '-p', str(port),
    '-U', user,
    '-d', 'postgres',
    '-f', '__GLOBALS_PATH__'
]
subprocess.run(cmd, check=True, env=env)
PY
fi

systemctl restart '__SERVICE_NAME__'
systemctl is-active '__SERVICE_NAME__' >/dev/null
curl -fsS http://127.0.0.1:8000/health >/dev/null

echo 'Restore completed successfully.'
'@

$remoteCommand = $remoteCommand.Replace('__REMOTE_RESTORE_DIR__', $remoteRestoreDir)
$remoteCommand = $remoteCommand.Replace('__REMOTE_ARCHIVE_PATH__', $remoteArchivePath)
$remoteCommand = $remoteCommand.Replace('__REMOTE_PROJECT_PATH__', $RemoteProjectPath)
$remoteCommand = $remoteCommand.Replace('__RESTORE_DB_FLAG__', $restoreDbFlag)
$remoteCommand = $remoteCommand.Replace('__RESTORE_GLOBALS_FLAG__', $restoreGlobalsFlag)
$remoteCommand = $remoteCommand.Replace('__DUMP_PATH__', "$remoteRestoreDir/extracted/charity_db.dump")
$remoteCommand = $remoteCommand.Replace('__GLOBALS_PATH__', "$remoteRestoreDir/extracted/charity_globals.sql")
$remoteCommand = $remoteCommand.Replace('__SERVICE_NAME__', $ServiceName)
$remoteCommand = $remoteCommand -replace "`r", ""

if ($WhatIf) {
    Write-Host "Dry run. The following restore would be performed:"
    Write-Host "  Server: $ServerHost"
    Write-Host "  Local archive: $BackupArchivePath"
    Write-Host "  Remote restore dir: $remoteRestoreDir"
    Write-Host "  Restore database: $RestoreDatabase"
    Write-Host "  Restore globals/roles: $RestoreGlobals"
    return
}

Write-Host "Uploading backup archive to $ServerHost..."
Invoke-NativeChecked -FilePath "ssh" -Arguments @(
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "ConnectTimeout=15",
    "$UserName@$ServerHost",
    "mkdir -p '$remoteRestoreDir'"
) -ErrorMessage "Failed to create remote restore directory"
Invoke-NativeChecked -FilePath "scp" -Arguments @(
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "ConnectTimeout=15",
    $BackupArchivePath,
    "${UserName}@${ServerHost}:${remoteArchivePath}"
) -ErrorMessage "Failed to upload backup archive"

Write-Host "Running restore on production host..."
Invoke-NativeChecked -FilePath "ssh" -Arguments @(
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "ConnectTimeout=15",
    "$UserName@$ServerHost",
    $remoteCommand
) -ErrorMessage "Remote restore command failed"

Write-Host "Restore finished and service health check passed."
