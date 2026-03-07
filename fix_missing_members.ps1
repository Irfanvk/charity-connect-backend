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
    Write-Host "3. Run this script again after psql is available" -ForegroundColor White
    exit 1
}

# Run the SQL script
Write-Host ""
Write-Host "Running SQL fix script..." -ForegroundColor Cyan

try {
    # Try to execute the SQL directly so this script is self-contained
    $sql = @'
DO $$
DECLARE
    v_user_id INT;
    v_username TEXT;
    v_last_member_code TEXT;
    v_next_member_code TEXT;
    v_code_number INT;
BEGIN
    FOR v_user_id, v_username IN
        SELECT u.id, u.username
        FROM users u
        LEFT JOIN members m ON m.user_id = u.id
        WHERE LOWER(u.role::text) = 'member'
          AND u.is_active = true
          AND m.id IS NULL
    LOOP
        SELECT member_code INTO v_last_member_code
        FROM members
        ORDER BY id DESC
        LIMIT 1;

        IF v_last_member_code IS NULL THEN
            v_next_member_code := 'MEM0001';
        ELSE
            v_code_number := CAST(SUBSTRING(v_last_member_code FROM 4) AS INT);
            v_next_member_code := 'MEM' || LPAD((v_code_number + 1)::TEXT, 4, '0');
        END IF;

        INSERT INTO members (user_id, member_code, monthly_amount, status, address)
        VALUES (v_user_id, v_next_member_code, 0.0, 'active', NULL);
    END LOOP;
END $$;

SELECT 
    u.id as user_id,
    u.username,
    u.email,
    m.id as member_id,
    m.member_code,
    m.status
FROM users u
LEFT JOIN members m ON m.user_id = u.id
WHERE LOWER(u.role::text) = 'member'
ORDER BY u.id;
'@

    $result = psql -U charity_user -d charity_connect -c $sql 2>&1
    
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
        Write-Host "Then run the SQL block shown in this script manually" -ForegroundColor Cyan
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
