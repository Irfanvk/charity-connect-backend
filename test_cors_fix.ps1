Write-Host "Testing CORS fix..." -ForegroundColor Green

# Health check
$health = Invoke-WebRequest -Uri "http://localhost:8000/health" -ErrorAction SilentlyContinue
Write-Host "Backend status: $($health.StatusCode)"

# OPTIONS preflight test
$options = Invoke-WebRequest -Uri "http://localhost:8000/challans/1/approve" -Method OPTIONS -Headers @{"Origin"="http://localhost:5173"} -ErrorAction SilentlyContinue
$methods = $options.Headers["Access-Control-Allow-Methods"]
Write-Host "Allowed methods: $methods"

if ($methods -like "*PATCH*") {
    Write-Host "SUCCESS: PATCH is allowed!" -ForegroundColor Green
} else {
    Write-Host "ERROR: PATCH not found in allowed methods" -ForegroundColor Red
}
