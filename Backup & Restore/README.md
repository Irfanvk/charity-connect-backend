# Database Backup, Verification, and Restore Workflow

This folder contains scripts for disaster recovery of your CharityHub production database.

## What's Included

- **backup_production.ps1** — Creates a timestamped PostgreSQL database backup on the production server and downloads it to your PC
- **verify_backup.ps1** — Validates backup integrity, checks file structure, and confirms the dump is restorable
- **restore_production_backup.ps1** — Restores a backup to the production server (or a different PostgreSQL instance)

## Quick Start

### 1. Create a Backup

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\backup_production.ps1
```

Or double-click **backup_production.cmd**

Output:
```
Creating production backup on 187.124.20.219...
root@187.124.20.219's password: [enter password]

Downloading backup archive to E:\CharityHub\Backups\charity-production\charity-prod-db-20260724_021345.tar.gz...
Backup completed successfully.
Saved to: E:\CharityHub\Backups\charity-production\charity-prod-db-20260724_021345.tar.gz
Checksum verified: abc123...
```

### 2. Verify the Backup

After backup completes, verify it:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\verify_backup.ps1 -BackupArchivePath "E:\CharityHub\Backups\charity-production\charity-prod-db-20260724_021345.tar.gz"
```

Or:

```cmd
verify_backup.cmd "E:\CharityHub\Backups\charity-production\charity-prod-db-20260724_021345.tar.gz"
```

Output:
```
=== PostgreSQL Backup Verification ===

Archive: E:\CharityHub\Backups\charity-production\charity-prod-db-20260724_021345.tar.gz
Size: 45.23 MB
Created: 7/24/2026 2:13:45 PM

Step 1: Verify SHA256 Checksum
✓ Checksum verification PASSED
  SHA256: abc123...

Step 2: Extract and Inspect Archive
  - charity_db.dump (42.15 MB)
  - backup_manifest.txt (0.005 MB)

Step 3: Verify Dump File
✓ Database dump found
  Size: 42.15 MB
  Format: PostgreSQL custom format (valid)

Step 4: Verify Manifest
✓ Backup manifest found:
  Backup started at 2026-07-24T02:13:45Z
  Project path: /root/charity-connect-backend
  Git commit: 434bb6a
  Backup scope: database-only

Step 5: Check for Globals Dump
⚠ Globals dump not found (backup created with limited permissions)
  This is normal if backup user is not a superuser.

=== Verification Summary ===
✓ Archive is valid and can be restored
```

### 3. Restore the Backup

**WARNING: Restoring to production WILL overwrite the live database.**

To restore to production:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\restore_production_backup.ps1 `
  -BackupArchivePath "E:\CharityHub\Backups\charity-production\charity-prod-db-20260724_021345.tar.gz"
```

Or with globals (if included):

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\restore_production_backup.ps1 `
  -BackupArchivePath "E:\CharityHub\Backups\charity-production\charity-prod-db-20260724_021345.tar.gz" `
  -RestoreGlobals $true
```

Or dry-run (preview without changes):

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\restore_production_backup.ps1 `
  -BackupArchivePath "E:\CharityHub\Backups\charity-production\charity-prod-db-20260724_021345.tar.gz" `
  -WhatIf
```

## What Gets Backed Up

- **Database schema** — all tables, indexes, constraints
- **Database data** — all rows in every table
- **Large objects** — binary files stored in PostgreSQL
- **Backup manifest** — metadata (timestamp, git commit, scope)
- **Globals (optional)** — roles/users (only if backup user is a superuser)

What is **NOT** backed up:
- Application code (lives in Git on GitHub, synced to production via git pull)
- Uploaded files (avatars, payment proofs, etc. stored on Cloudinary)
- Session data / temporary files

## Verifying Without Restoring

If you want to verify a backup is valid **without restoring to production**, use **verify_backup.ps1**. It:

1. ✓ Checks SHA256 checksumintegrity
2. ✓ Extracts and lists archive contents
3. ✓ Validates the dump file format (PostgreSQL custom format magic bytes)
4. ✓ Shows backup metadata from manifest
5. ✓ Reports whether globals dump is included

## File Format

The backup archive is a gzipped tar file containing:

```
charity-prod-db-20260724_021345.tar.gz
├── charity_db.dump              (PostgreSQL custom format, binary)
├── backup_manifest.txt          (human-readable metadata)
└── charity_globals.sql          (SQL script for roles, if available)
```

The **.dump** file is PostgreSQL's custom binary format (`pg_dump -F custom`), which:
- ✓ Is compressed internally
- ✓ Preserves all data and schema
- ✓ Can be restored with `pg_restore` command
- ✓ Supports selective restore (e.g., restore only specific tables)
- ✓ Is faster to restore than SQL text format

## Backup Frequency

Recommended:
- **Weekly** — automatic via Windows Task Scheduler (can be added)
- **Monthly** — archive and store offline

## Storage

Currently backups are stored locally at:
```
E:\CharityHub\Backups\charity-production\
```

Recommended:
- Keep at least **3 recent backups** locally
- Copy **1 monthly backup** to an external drive or cloud storage (OneDrive, Google Drive, etc.)
- Keep credentials and this workflow document in your local vault only

## Disaster Recovery Checklist

If production server goes down:

1. ✓ Verify the backup is intact (run verify_backup.ps1)
2. ✓ Get SSH access to a replacement PostgreSQL server (or spin up new Hostinger server)
3. ✓ Transfer backup archive to the new server
4. ✓ Extract: `tar -xzf charity-prod-db-*.tar.gz`
5. ✓ Restore: `pg_restore -d charity_connect -U charity_user charity_db.dump`
6. ✓ Pull latest code: `cd /root/charity-connect-backend && git pull origin main`
7. ✓ Restart service: `systemctl restart charity.service`
8. ✓ Test: `curl http://127.0.0.1:8000/health`

Total recovery time: **~15 minutes** (depending on database size and network speed)

## Troubleshooting

### "Checksum verification failed"
- Archive was corrupted during download
- Solution: Run backup again

### "Database dump not found in archive"
- Backup was incomplete
- Solution: Run backup again, check server logs for errors

### "PostgreSQL custom format (invalid)"
- Dump file is not a valid PostgreSQL backup
- Solution: Run backup again

### "pg_restore: error: could not connect to database"
- PostgreSQL server is not running or connection details wrong
- Solution: Check that PostgreSQL is running and DATABASE_URL is correct

## Manual Restore (Without Script)

If you need to restore manually:

```bash
# On the server:
tar -xzf charity-prod-db-20260724_021345.tar.gz
pg_restore --clean --if-exists --no-owner -d charity_connect charity_db.dump
```

`--clean` drops existing objects first (safe for overwrites)
`--if-exists` doesn't error if objects don't exist
`--no-owner` skips owner restoration (uses current user as owner)

## Questions?

Refer to:
- [PostgreSQL pg_dump documentation](https://www.postgresql.org/docs/current/app-pgdump.html)
- [PostgreSQL pg_restore documentation](https://www.postgresql.org/docs/current/app-pgrestore.html)
- Your local `APP_PRIVATE_VAULT` for server credentials and deployment notes
