# Rebuild Flutter web UI into Django static/ with REAL Django auth enabled.
# From Pastor-AI-main:
#   .\rebuild_web.ps1
#
# Optional mock UI-only auth (any password works):
#   .\rebuild_web.ps1 -UseMockAuth

param(
    [string]$FlutterRoot = "C:\src\flutter\flutter",
    [switch]$UseMockAuth
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$App = Join-Path $Root "flutter_application_1"
$Static = Join-Path $Root "static"
$FlutterBat = Join-Path $FlutterRoot "bin\flutter.bat"

function Assert-Path($Path, $Label) {
    if (-not (Test-Path $Path)) {
        throw "$Label not found: $Path"
    }
}

Assert-Path $FlutterBat "flutter.bat"
Assert-Path (Join-Path $App "pubspec.yaml") "Flutter app"
Assert-Path (Join-Path $App "lib\main.dart") "main.dart"

$mainDart = Get-Content -Raw (Join-Path $App "lib\main.dart")
if ($mainDart -notmatch "LoginScreen") {
    throw "lib\main.dart does not contain LoginScreen. You may be on the wrong branch/files."
}

Write-Host "Using Flutter: $FlutterBat"
Write-Host "App:           $App"
Write-Host "Output:        $Static"
Write-Host ""
Write-Host "If build mentions symlinks, enable Developer Mode first:"
Write-Host "  start ms-settings:developers"
Write-Host ""

Set-Location $App

Write-Host "==> flutter pub get"
& $FlutterBat pub get
if ($LASTEXITCODE -ne 0) { throw "flutter pub get failed" }

Write-Host "==> flutter build web"
$dartDefines = @()
if ($UseMockAuth) {
    Write-Host "    USE_MOCK_AUTH=true (UI demo only; Django auth NOT used)"
    $dartDefines += "--dart-define=USE_MOCK_AUTH=true"
} else {
    Write-Host "    USE_MOCK_AUTH=false (real Django /api/auth/*)"
    $dartDefines += "--dart-define=USE_MOCK_AUTH=false"
}

$buildArgs = @(
    "build", "web",
    "--release",
    "--base-href", "/static/",
    "--no-wasm-dry-run",
    "--pwa-strategy=none"
) + $dartDefines

& $FlutterBat @buildArgs
if ($LASTEXITCODE -ne 0) { throw "flutter build web failed - UI was NOT updated" }

$BuildWeb = Join-Path $App "build\web"
$BuiltJs = Join-Path $BuildWeb "main.dart.js"
Assert-Path $BuiltJs "build\web\main.dart.js"

$builtText = Get-Content -Raw $BuiltJs
if ($builtText -notmatch "LoginScreen|Sign in to save|api/auth/login") {
    throw "Build finished, but the new login UI is NOT inside main.dart.js. Check lib\main.dart, then rebuild."
}

Write-Host "==> Replacing static\ with fresh build"
New-Item -ItemType Directory -Force -Path $Static | Out-Null
Get-ChildItem -Force $Static -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
Copy-Item -Recurse -Force (Join-Path $BuildWeb "*") $Static

$StaticJs = Join-Path $Static "main.dart.js"
Assert-Path $StaticJs "static\main.dart.js"
$staticInfo = Get-Item $StaticJs
$staticText = Get-Content -Raw $StaticJs
if ($staticText -notmatch "LoginScreen|Sign in to save|api/auth/login") {
    throw "Copy finished, but static\main.dart.js still lacks the new login UI."
}

Write-Host ""
Write-Host "SUCCESS - new UI is in static\"
if ($UseMockAuth) {
    Write-Host "  MODE: MOCK auth (any email/password will appear to work)"
} else {
    Write-Host "  MODE: REAL Django auth (must Register first, then Sign in)"
}
Write-Host ("  main.dart.js size : {0:N0} bytes" -f $staticInfo.Length)
Write-Host ("  last write time   : {0}" -f $staticInfo.LastWriteTime)
Write-Host ""
Write-Host "Next:"
Write-Host "  python manage.py migrate"
Write-Host "  python manage.py runserver"
Write-Host "  Open http://127.0.0.1:8000/ -> Clear site data -> Ctrl+Shift+R"
Write-Host "  Create one (register) -> Sign out -> Sign in with same credentials"
