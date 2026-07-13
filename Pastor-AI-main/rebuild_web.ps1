# One-command Flutter web rebuild for Django static/
# From Pastor-AI-main:
#   .\rebuild_web.ps1
#
# Optional custom Flutter SDK root (folder that CONTAINS bin\flutter.bat):
#   .\rebuild_web.ps1 -FlutterRoot "C:\src\flutter\flutter"

param(
    [string]$FlutterRoot = "C:\src\flutter\flutter"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$App = Join-Path $Root "flutter_application_1"
$Static = Join-Path $Root "static"
$FlutterBat = Join-Path $FlutterRoot "bin\flutter.bat"

if (-not (Test-Path $FlutterBat)) {
    Write-Host "ERROR: flutter.bat not found at:"
    Write-Host "  $FlutterBat"
    Write-Host "Pass the folder that contains bin\flutter.bat, for example:"
    Write-Host '  .\rebuild_web.ps1 -FlutterRoot "C:\src\flutter\flutter"'
    exit 1
}

Write-Host "1) Using Flutter: $FlutterBat"
Write-Host "2) If build fails mentioning symlinks, enable Developer Mode:"
Write-Host "     start ms-settings:developers"
Write-Host ""

Set-Location $App
& $FlutterBat pub get
if ($LASTEXITCODE -ne 0) { throw "flutter pub get failed" }

& $FlutterBat build web --release --base-href /static/ --no-wasm-dry-run
if ($LASTEXITCODE -ne 0) { throw "flutter build web failed" }

$BuildWeb = Join-Path $App "build\web"
if (-not (Test-Path $BuildWeb)) { throw "Missing build output: $BuildWeb" }

Write-Host "3) Copying build\web -> static\"
New-Item -ItemType Directory -Force -Path $Static | Out-Null
Get-ChildItem -Force $Static | Remove-Item -Recurse -Force
Copy-Item -Recurse -Force (Join-Path $BuildWeb "*") $Static

Write-Host ""
Write-Host "SUCCESS. Now run Django (from Pastor-AI-main):"
Write-Host "  python manage.py migrate"
Write-Host "  python manage.py runserver"
Write-Host "Then open http://127.0.0.1:8000/ and hard-refresh (Ctrl+Shift+R)."
