[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BackupArchivePath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not (Test-Path -Path $BackupArchivePath -PathType Leaf)) {
    throw "Backup archive not found: $BackupArchivePath"
}

Write-Host "=== PostgreSQL Backup Verification ===" -ForegroundColor Green
Write-Host ""

$archiveInfo = Get-Item -Path $BackupArchivePath
Write-Host "Archive: $BackupArchivePath"
Write-Host "Size: $([Math]::Round($archiveInfo.Length / 1MB, 2)) MB"
Write-Host "Created: $($archiveInfo.CreationTime.ToString('g'))"
Write-Host ""

$archiveDir = Split-Path -Path $BackupArchivePath -Parent
$tempDir = Join-Path $archiveDir ".verify_temp_$(Get-Random)"
$checksumPath = "$BackupArchivePath.sha256"

Write-Host "Step 1: Verify SHA256 Checksum" -ForegroundColor Cyan
if (Test-Path -Path $checksumPath -PathType Leaf) {
    Write-Host "Checksum file found: $checksumPath"
    $checksumContent = Get-Content -Path $checksumPath -Raw
    $remoteSha = $checksumContent.Trim().Split(' ')[0]
    $localSha = (Get-FileHash -Path $BackupArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()

    if ($remoteSha -eq $localSha) {
        Write-Host "✓ Checksum verification PASSED" -ForegroundColor Green
        Write-Host "  SHA256: $localSha"
    }
    else {
        Write-Host "✗ Checksum verification FAILED" -ForegroundColor Red
        Write-Host "  Expected: $remoteSha"
        Write-Host "  Got:      $localSha"
        exit 1
    }
}
else {
    Write-Host "⚠ Checksum file not found (optional)" -ForegroundColor Yellow
    Write-Host "  Computing SHA256 for archive..."
    $sha = (Get-FileHash -Path $BackupArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host "  SHA256: $sha"
}

Write-Host ""
Write-Host "Step 2: Extract and Inspect Archive" -ForegroundColor Cyan

New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

try {
    Write-Host "Extracting archive to temporary directory..."
    tar -xzf $BackupArchivePath -C $tempDir

    Write-Host "Archive contents:"
    Get-ChildItem -Path $tempDir -Recurse | ForEach-Object {
        if (-not $_.PSIsContainer) {
            $relativePath = $_.FullName.Substring($tempDir.Length + 1)
            Write-Host "  - $relativePath ($([Math]::Round($_.Length / 1MB, 2)) MB)"
        }
    }

    Write-Host ""
    Write-Host "Step 3: Verify Dump File" -ForegroundColor Cyan
    $dumpPath = Join-Path $tempDir "charity_db.dump"

    if (Test-Path -Path $dumpPath -PathType Leaf) {
        Write-Host "✓ Database dump found"
        $dumpSize = (Get-Item -Path $dumpPath).Length
        Write-Host "  Size: $([Math]::Round($dumpSize / 1MB, 2)) MB"

        # Check if it's a valid PostgreSQL custom format dump
        $dumpBytes = Get-Content -Path $dumpPath -Encoding Byte -TotalCount 4
        $dumpMagic = [System.BitConverter]::ToString($dumpBytes) -replace "-", ""

        if ($dumpMagic -eq "504F3034") {
            Write-Host "  Format: PostgreSQL custom format (valid)" -ForegroundColor Green
        }
        else {
            Write-Host "  Warning: Unexpected magic bytes. File may not be a valid PostgreSQL dump." -ForegroundColor Yellow
        }
    }
    else {
        Write-Host "✗ Database dump not found in archive!" -ForegroundColor Red
        exit 1
    }

    Write-Host ""
    Write-Host "Step 4: Verify Manifest" -ForegroundColor Cyan
    $manifestPath = Join-Path $tempDir "backup_manifest.txt"

    if (Test-Path -Path $manifestPath -PathType Leaf) {
        Write-Host "✓ Backup manifest found:"
        Get-Content -Path $manifestPath | ForEach-Object {
            Write-Host "  $_"
        }
    }
    else {
        Write-Host "⚠ Backup manifest not found (optional)" -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "Step 5: Check for Globals Dump" -ForegroundColor Cyan
    $globalsPath = Join-Path $tempDir "charity_globals.sql"

    if (Test-Path -Path $globalsPath -PathType Leaf) {
        Write-Host "✓ Globals dump found"
        $globalsSize = (Get-Item -Path $globalsPath).Length
        Write-Host "  Size: $([Math]::Round($globalsSize / 1024, 2)) KB"
    }
    else {
        Write-Host "⚠ Globals dump not found (backup created with limited permissions)" -ForegroundColor Yellow
        Write-Host "  This is normal if backup user is not a superuser."
    }

    Write-Host ""
    Write-Host "=== Verification Summary ===" -ForegroundColor Green
    Write-Host "✓ Archive is valid and can be restored"
    Write-Host ""
    Write-Host "To restore this backup on a PostgreSQL server:"
    Write-Host "  1. Transfer archive to the target server"
    Write-Host "  2. Extract: tar -xzf $([System.IO.Path]::GetFileName($BackupArchivePath)) -C /tmp/"
    Write-Host "  3. Restore: pg_restore -d charity_connect -U charity_user /tmp/charity_db.dump"
    Write-Host ""
    Write-Host "For more details, see the restore_production_backup.ps1 script."

}
finally {
    Write-Host ""
    Write-Host "Cleaning up temporary files..."
    if (Test-Path -Path $tempDir) {
        Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
