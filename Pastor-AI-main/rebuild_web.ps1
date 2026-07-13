# Rebuild Flutter web UI into Django static/ and VERIFY the new UI is present.
# From Pastor-AI-main, run ONE command:
#   .\rebuild_web.ps1
#
# Your Flutter bat path is already the default:
#   C:\src\flutter\flutter\bin\flutter.bat

param(
    [string]$FlutterRoot = "C:\src\flutter\flutter"
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

# Confirm the source UI actually has the new login screen before building.
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

# --pwa-strategy=none avoids Flutter service-worker caching the OLD UI forever.
Write-Host "==> flutter build web"
& $FlutterBat build web --release --base-href /static/ --no-wasm-dry-run --pwa-strategy=none
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
Write-Host ("  main.dart.js size : {0:N0} bytes" -f $staticInfo.Length)
Write-Host ("  last write time   : {0}" -f $staticInfo.LastWriteTime)
Write-Host ""
Write-Host "Next commands (from Pastor-AI-main):"
Write-Host "  python manage.py migrate"
Write-Host "  python manage.py runserver"
Write-Host ""
Write-Host "Then in Chrome/Edge:"
Write-Host "  1. Open http://127.0.0.1:8000/"
Write-Host "  2. Press F12 -> Application -> Service Workers -> Unregister (if any)"
Write-Host "  3. Application -> Storage -> Clear site data"
Write-Host "  4. Hard refresh with Ctrl+Shift+R"
