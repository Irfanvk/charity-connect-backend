# E2E Smoke Test Suite
# Run: .\e2e_smoke_test.ps1

$baseUrl = "http://127.0.0.1:8000"
$testResults = @()

function Test-Endpoint {
    param(
        [string]$Name,
        [string]$Method,
        [string]$Url,
        [hashtable]$Headers = @{},
        [object]$Body = $null,
        [int]$ExpectedStatus = 200
    )
    
    Write-Host "`n[$Name]" -ForegroundColor Cyan
    Write-Host "$Method $Url"
    
    try {
        $params = @{
            Uri = "$baseUrl$Url"
            Method = $Method
            Headers = $Headers
            UseBasicParsing = $true
        }
        
        if ($Body) {
            $params.Body = ($Body | ConvertTo-Json -Depth 10)
            $params.ContentType = "application/json"
        }
        
        $response = Invoke-WebRequest @params -ErrorAction Stop
        
        if ($response.StatusCode -eq $ExpectedStatus) {
            Write-Host "✅ PASS - Status: $($response.StatusCode)" -ForegroundColor Green
            $script:testResults += @{Name=$Name; Status="PASS"; Code=$response.StatusCode}
            return $response.Content | ConvertFrom-Json
        } else {
            Write-Host "❌ FAIL - Expected: $ExpectedStatus, Got: $($response.StatusCode)" -ForegroundColor Red
            $script:testResults += @{Name=$Name; Status="FAIL"; Code=$response.StatusCode}
            return $null
        }
    } catch {
        $statusCode = if ($_.Exception.Response) { $_.Exception.Response.StatusCode.value__ } else { "N/A" }
        Write-Host "❌ ERROR - Status: $statusCode" -ForegroundColor Red
        Write-Host $_.Exception.Message -ForegroundColor Red
        $script:testResults += @{Name=$Name; Status="ERROR"; Code=$statusCode}
        return $null
    }
}

Write-Host "========================================" -ForegroundColor Yellow
Write-Host "CharityConnect E2E Smoke Test Suite" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Yellow

# Test 1: Health Check
$health = Test-Endpoint -Name "Health Check" -Method "GET" -Url "/health"

# Test 2: Root Endpoint
$root = Test-Endpoint -Name "Root Endpoint" -Method "GET" -Url "/"

# Test 3: Login as Member (using existing user)
Write-Host "`n--- Testing Member Flow ---" -ForegroundColor Magenta
$memberLogin = Test-Endpoint `
    -Name "Member Login" `
    -Method "POST" `
    -Url "/auth/login" `
    -Body @{
        username = "Irfanvk"
        password = "password123"
    }

if ($memberLogin -and $memberLogin.access_token) {
    $memberToken = $memberLogin.access_token
    $memberHeaders = @{
        "Authorization" = "Bearer $memberToken"
    }
    
    # Test 4: Get Current User (Member)
    $memberMe = Test-Endpoint `
        -Name "Get Member /auth/me" `
        -Method "GET" `
        -Url "/auth/me" `
        -Headers $memberHeaders
    
    # Test 5: Get Challans (Member - should see own only)
    $memberChallans = Test-Endpoint `
        -Name "Get Challans (Member)" `
        -Method "GET" `
        -Url "/challans/" `
        -Headers $memberHeaders
    
    if ($memberChallans) {
        Write-Host "  Member sees $($memberChallans.Count) challans" -ForegroundColor Gray
    }
    
    # Test 6: Get Members List (Member - should see self only)
    $memberMembers = Test-Endpoint `
        -Name "Get Members (Member)" `
        -Method "GET" `
        -Url "/members/" `
        -Headers $memberHeaders
    
    if ($memberMembers) {
        Write-Host "  Member sees $($memberMembers.Count) members" -ForegroundColor Gray
    }
    
    # Test 7: Create Challan (Member)
    $newChallan = Test-Endpoint `
        -Name "Create Challan (Member)" `
        -Method "POST" `
        -Url "/challans/" `
        -Headers $memberHeaders `
        -Body @{
            type = "monthly"
            month = "2026-03"
            amount = 500.0
            payment_method = "online"
            notes = "E2E Test Challan"
        } `
        -ExpectedStatus 201
    
    $challanId = if ($newChallan) { $newChallan.id } else { $null }
}

# Test 8: Login as Admin
Write-Host "`n--- Testing Admin Flow ---" -ForegroundColor Magenta
$adminLogin = Test-Endpoint `
    -Name "Admin Login" `
    -Method "POST" `
    -Url "/auth/login" `
    -Body @{
        username = "admin1"
        password = "admin123"
    }

if ($adminLogin -and $adminLogin.access_token) {
    $adminToken = $adminLogin.access_token
    $adminHeaders = @{
        "Authorization" = "Bearer $adminToken"
    }
    
    # Test 9: Get Current User (Admin)
    $adminMe = Test-Endpoint `
        -Name "Get Admin /auth/me" `
        -Method "GET" `
        -Url "/auth/me" `
        -Headers $adminHeaders
    
    # Test 10: Get All Challans (Admin - should see all)
    $adminChallans = Test-Endpoint `
        -Name "Get All Challans (Admin)" `
        -Method "GET" `
        -Url "/challans/?sort_by=created_at&sort_order=desc" `
        -Headers $adminHeaders
    
    if ($adminChallans) {
        Write-Host "  Admin sees $($adminChallans.Count) challans" -ForegroundColor Gray
    }
    
    # Test 11: Get All Members (Admin - should see all)
    $adminMembers = Test-Endpoint `
        -Name "Get All Members (Admin)" `
        -Method "GET" `
        -Url "/members/" `
        -Headers $adminHeaders
    
    if ($adminMembers) {
        Write-Host "  Admin sees $($adminMembers.Count) members" -ForegroundColor Gray
    }
    
    # Test 12: Get Users (Admin Only)
    $users = Test-Endpoint `
        -Name "Get Users (Admin)" `
        -Method "GET" `
        -Url "/users/" `
        -Headers $adminHeaders
    
    # Test 13: Approve Challan (Admin)
    if ($challanId) {
        $approved = Test-Endpoint `
            -Name "Approve Challan (Admin)" `
            -Method "PATCH" `
            -Url "/challans/$challanId/approve" `
            -Headers $adminHeaders `
            -Body @{}
        
        if ($approved) {
            Write-Host "  Challan ID $challanId approved successfully" -ForegroundColor Gray
            Write-Host "  Status: $($approved.status), Approved At: $($approved.approved_at)" -ForegroundColor Gray
        }
    }
    
    # Test 14: Get Pending Challans
    $pendingChallans = Test-Endpoint `
        -Name "Get Pending Challans (Admin)" `
        -Method "GET" `
        -Url "/challans/?status=pending" `
        -Headers $adminHeaders
    
    # Test 15: Get Notifications (Admin)
    $notifications = Test-Endpoint `
        -Name "Get Notifications (Admin)" `
        -Method "GET" `
        -Url "/notifications/" `
        -Headers $adminHeaders
    
    # Test 16: Get Unread Count
    $unreadCount = Test-Endpoint `
        -Name "Get Unread Count (Admin)" `
        -Method "GET" `
        -Url "/notifications/unread/count" `
        -Headers $adminHeaders
}

# Print Summary
Write-Host "`n========================================" -ForegroundColor Yellow
Write-Host "Test Summary" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Yellow

$passed = ($testResults | Where-Object { $_.Status -eq "PASS" }).Count
$failed = ($testResults | Where-Object { $_.Status -in @("FAIL", "ERROR") }).Count
$total = $testResults.Count

Write-Host "`nTotal Tests: $total" -ForegroundColor Cyan
Write-Host "Passed: $passed" -ForegroundColor Green
Write-Host "Failed: $failed" -ForegroundColor $(if ($failed -gt 0) { "Red" } else { "Green" })

if ($failed -eq 0) {
    Write-Host "`n✅ ALL TESTS PASSED!" -ForegroundColor Green
} else {
    Write-Host "`n❌ SOME TESTS FAILED" -ForegroundColor Red
    Write-Host "`nFailed Tests:" -ForegroundColor Red
    $testResults | Where-Object { $_.Status -in @("FAIL", "ERROR") } | ForEach-Object {
        Write-Host "  - $($_.Name) (Status: $($_.Code))" -ForegroundColor Red
    }
}

Write-Host "`n========================================" -ForegroundColor Yellow
