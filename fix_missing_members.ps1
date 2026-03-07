# Fix Missing Member Records - PowerShell Script
# Run this script to create Member records for users who don't have them

Write-Host "Fixing Missing Member Records..." -ForegroundColor Green
Write-Host "=================================" -ForegroundColor Green

# Get database connection details from .env
$envFile = ".\.env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^DATABASE_URL=(.+)$') {
            $dbUrl = $matches[1]
            Write-Host "Found DATABASE_URL in .env" -ForegroundColor Cyan
        }
    }
}

# Check if psql is available
$psqlInstalled = Get-Command psql -ErrorAction SilentlyContinue

# Fallback: try to discover psql.exe from standard PostgreSQL install path
if (-not $psqlInstalled) {
    $candidate = Get-ChildItem "C:\Program Files\PostgreSQL" -Directory -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending |
        ForEach-Object { Join-Path $_.FullName "bin\psql.exe" } |
        Where-Object { Test-Path $_ } |
        Select-Object -First 1

    if ($candidate) {
        $candidateDir = Split-Path $candidate -Parent
        $env:Path = "$candidateDir;$env:Path"
        $psqlInstalled = Get-Command psql -ErrorAction SilentlyContinue
        Write-Host "Found psql at: $candidate" -ForegroundColor Cyan
    }
}

if (-not $psqlInstalled) {
    Write-Host "ERROR: psql command not found." -ForegroundColor Red
    Write-Host "Please install PostgreSQL client tools or run the SQL manually." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Manual steps:" -ForegroundColor Cyan
    Write-Host "1. Open pgAdmin or your PostgreSQL client" -ForegroundColor White
    Write-Host "2. Connect to database 'charity_connect'" -ForegroundColor White
    Write-Host "3. Run the script: fix_missing_members.sql" -ForegroundColor White
    exit 1
}

# Run the SQL script
Write-Host ""
Write-Host "Running SQL fix script..." -ForegroundColor Cyan

try {
    # Try to execute the SQL
    $result = psql -U charity_user -d charity_connect -f .\fix_missing_members.sql 2>&1
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "SUCCESS! Member records created." -ForegroundColor Green
        Write-Host $result
        Write-Host ""
        Write-Host "Next steps:" -ForegroundColor Yellow
        Write-Host "1. Refresh your browser at http://localhost:5173" -ForegroundColor White
        Write-Host "2. Try creating a challan again" -ForegroundColor White
    } else {
        Write-Host ""
        Write-Host "ERROR: Script execution failed" -ForegroundColor Red
        Write-Host $result
        Write-Host ""
        Write-Host "Try running manually:" -ForegroundColor Yellow
        Write-Host "psql -U charity_user -d charity_connect" -ForegroundColor Cyan
        Write-Host "Then paste the contents of fix_missing_members.sql" -ForegroundColor Cyan
    }
} catch {
    Write-Host ""
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ""
    Write-Host "Alternative: Run this SQL command in pgAdmin:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "INSERT INTO members (user_id, member_code, monthly_amount, status)" -ForegroundColor Cyan
    Write-Host "SELECT u.id, 'MEM' || LPAD((COALESCE(MAX(m2.id), 0) + 1)::TEXT, 4, '0'), 0.0, 'active'" -ForegroundColor Cyan
    Write-Host "FROM users u" -ForegroundColor Cyan
    Write-Host "CROSS JOIN (SELECT MAX(id) as id FROM members) m2" -ForegroundColor Cyan
    Write-Host "LEFT JOIN members m ON m.user_id = u.id" -ForegroundColor Cyan
    Write-Host "WHERE u.role = 'member' AND m.id IS NULL;" -ForegroundColor Cyan
}

Write-Host ""
Write-Host "=================================" -ForegroundColor Green
