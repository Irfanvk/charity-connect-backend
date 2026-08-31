[CmdletBinding()]
param(
    [string]$ServerHost = "187.124.20.219",
    [string]$UserName = "root",
    [string]$RemoteProjectPath = "/root/charity-connect-backend",
    [string]$RemoteBackupRoot = "/root/backups/charity-production",
    [string]$LocalBackupRoot = "E:\CharityHub\Backups\charity-production",
    [string]$ArchiveNamePrefix = "charity-prod-db",
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

if (-not (Test-Path -Path $LocalBackupRoot)) {
    New-Item -ItemType Directory -Path $LocalBackupRoot -Force | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$remoteBackupDir = "$RemoteBackupRoot/$timestamp"
$archiveFileName = "$ArchiveNamePrefix-$timestamp.tar.gz"
$remoteArchivePath = "$remoteBackupDir/$archiveFileName"
$remoteChecksumPath = "$remoteArchivePath.sha256"
$localArchivePath = Join-Path $LocalBackupRoot $archiveFileName
$localChecksumPath = "$localArchivePath.sha256"

$remoteCommand = @'
set -e
mkdir -p '__REMOTE_BACKUP_DIR__'
cd '__REMOTE_PROJECT_PATH__'

printf 'Backup started at %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" > '__REMOTE_BACKUP_DIR__/backup_manifest.txt'
printf 'Project path: %s\n' '__REMOTE_PROJECT_PATH__' >> '__REMOTE_BACKUP_DIR__/backup_manifest.txt'
printf 'Git commit: %s\n' "$(git rev-parse HEAD 2>/dev/null || echo unknown)" >> '__REMOTE_BACKUP_DIR__/backup_manifest.txt'
printf 'Backup scope: database-only\n' >> '__REMOTE_BACKUP_DIR__/backup_manifest.txt'

python3 - <<'PY'
import os
import subprocess
from urllib.parse import urlparse

backup_path = '__REMOTE_BACKUP_DIR__/charity_db.dump'
globals_path = '__REMOTE_BACKUP_DIR__/charity_globals.sql'
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
    raise SystemExit('DATABASE_URL not found in remote environment. Backup aborted.')

parsed = urlparse(raw_db_url)
if parsed.scheme != 'postgresql' and parsed.scheme != 'postgres':
    raise SystemExit(f'Unsupported database URL scheme: {parsed.scheme}')

host = parsed.hostname or '127.0.0.1'
port = parsed.port or 5432
user = parsed.username or 'postgres'
db_name = parsed.path.lstrip('/') or 'postgres'
password = parsed.password or ''

env = os.environ.copy()
env['PGPASSWORD'] = password
dump_cmd = [
    'pg_dump',
    '--format=custom',
    '--blobs',
    '--serializable-deferrable',
    '--no-owner',
    '--no-privileges',
    '-h', host,
    '-p', str(port),
    '-U', user,
    '-d', db_name,
    '-f', backup_path,
]
subprocess.run(dump_cmd, check=True, env=env)

globals_cmd = [
    'pg_dumpall',
    '--globals-only',
    '-h', host,
    '-p', str(port),
    '-U', user,
    '-f', globals_path,
]
try:
    subprocess.run(globals_cmd, check=True, env=env)
except subprocess.CalledProcessError as e:
    print(f'Warning: Globals dump failed (likely due to permissions): {e}')
    print('Continuing with database dump only. Roles/users can be manually recreated if needed.')
PY

tar -czf '__REMOTE_ARCHIVE_PATH__' -C '__REMOTE_BACKUP_DIR__' charity_db.dump backup_manifest.txt charity_globals.sql 2>&1 | grep -v "Cannot stat" || true
sha256sum '__REMOTE_ARCHIVE_PATH__' > '__REMOTE_CHECKSUM_PATH__'
'@

$remoteCommand = $remoteCommand.Replace('__REMOTE_BACKUP_DIR__', $remoteBackupDir)
$remoteCommand = $remoteCommand.Replace('__REMOTE_PROJECT_PATH__', $RemoteProjectPath)
$remoteCommand = $remoteCommand.Replace('__REMOTE_ARCHIVE_PATH__', $remoteArchivePath)
$remoteCommand = $remoteCommand.Replace('__REMOTE_CHECKSUM_PATH__', $remoteChecksumPath)
$remoteCommand = $remoteCommand -replace "`r", ""

if ($WhatIf) {
    Write-Host "Dry run. The following backup would be created:"
    Write-Host "  Server: $ServerHost"
    Write-Host "  Remote backup dir: $remoteBackupDir"
    Write-Host "  Local archive path: $localArchivePath"
    Write-Host "  Scope: PostgreSQL database only"
    return
}

Write-Host "Creating production backup on $ServerHost..."
Invoke-NativeChecked -FilePath "ssh" -Arguments @(
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "ConnectTimeout=15",
    "$UserName@$ServerHost",
    $remoteCommand
) -ErrorMessage "Remote backup command failed"

Write-Host "Downloading backup archive to $localArchivePath..."
Invoke-NativeChecked -FilePath "scp" -Arguments @(
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "ConnectTimeout=15",
    "${UserName}@${ServerHost}:${remoteArchivePath}",
    $localArchivePath
) -ErrorMessage "Failed to download backup archive"
Invoke-NativeChecked -FilePath "scp" -Arguments @(
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "ConnectTimeout=15",
    "${UserName}@${ServerHost}:${remoteChecksumPath}",
    $localChecksumPath
) -ErrorMessage "Failed to download checksum file"

$remoteSha = (Get-Content -Path $localChecksumPath -Raw).Trim().Split(' ')[0]
$localSha = (Get-FileHash -Path $localArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()

if ($remoteSha -ne $localSha) {
    throw "Checksum verification failed. Remote SHA256 '$remoteSha' does not match local SHA256 '$localSha'."
}

Write-Host "Backup completed successfully."
Write-Host "Saved to: $localArchivePath"
Write-Host "Checksum verified: $localSha"
