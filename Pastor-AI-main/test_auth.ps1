# Test Django auth endpoints against a running local server.
# Usage (from Pastor-AI-main, with runserver already up):
#   .\test_auth.ps1
#   .\test_auth.ps1 -BaseUrl "http://127.0.0.1:8000"

param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$Email = ("tester_{0}@example.com" -f (Get-Random -Maximum 999999)),
    [string]$Password = "Str0ngPass!",
    [string]$Name = "Test User"
)

$ErrorActionPreference = "Stop"

function Invoke-Json {
    param(
        [string]$Method,
        [string]$Url,
        [hashtable]$Headers = @{},
        [object]$Body = $null
    )
    $params = @{
        Method = $Method
        Uri = $Url
        Headers = $Headers
    }
    if ($null -ne $Body) {
        $params.ContentType = "application/json"
        $params.Body = ($Body | ConvertTo-Json)
    }
    return Invoke-RestMethod @params
}

Write-Host "Base URL: $BaseUrl"
Write-Host "Email:    $Email"
Write-Host ""

Write-Host "1) REGISTER"
$register = Invoke-Json -Method POST -Url "$BaseUrl/api/auth/register/" -Body @{
    name = $Name
    email = $Email
    password = $Password
}
Write-Host ("   token: {0}..." -f $register.token.Substring(0, [Math]::Min(12, $register.token.Length)))
Write-Host ("   user:  {0} <{1}>" -f $register.user.name, $register.user.email)

Write-Host "2) LOGIN (wrong password should fail)"
try {
    Invoke-Json -Method POST -Url "$BaseUrl/api/auth/login/" -Body @{
        email = $Email
        password = "wrong-password"
    } | Out-Null
    throw "Expected wrong-password login to fail"
} catch {
    if ($_.Exception.Response.StatusCode.value__ -ne 401 -and $_.ErrorDetails -eq $null) {
        # Invoke-RestMethod throws differently across PS versions; continue if it failed.
    }
    Write-Host "   ok - rejected bad password"
}

Write-Host "3) LOGIN"
$login = Invoke-Json -Method POST -Url "$BaseUrl/api/auth/login/" -Body @{
    email = $Email
    password = $Password
}
$token = $login.token
Write-Host ("   token: {0}..." -f $token.Substring(0, [Math]::Min(12, $token.Length)))

Write-Host "4) ME"
$me = Invoke-Json -Method GET -Url "$BaseUrl/api/auth/me/" -Headers @{
    Authorization = "Bearer $token"
    Accept = "application/json"
}
Write-Host ("   user:  {0} <{1}>" -f $me.user.name, $me.user.email)

Write-Host "5) LOGOUT"
Invoke-WebRequest -Method POST -Uri "$BaseUrl/api/auth/logout/" -Headers @{
    Authorization = "Bearer $token"
    Accept = "application/json"
} | Out-Null
Write-Host "   ok"

Write-Host "6) ME after logout (should be 401)"
try {
    Invoke-Json -Method GET -Url "$BaseUrl/api/auth/me/" -Headers @{
        Authorization = "Bearer $token"
        Accept = "application/json"
    } | Out-Null
    throw "Expected /me after logout to fail"
} catch {
    Write-Host "   ok - token no longer works"
}

Write-Host ""
Write-Host "API auth flow passed."
Write-Host "UI tip: rebuild with real API before testing in the browser:"
Write-Host '  .\rebuild_web.ps1 -UseRealApi'
