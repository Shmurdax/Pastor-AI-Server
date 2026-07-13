# Rebuild the Flutter web app and copy it into Django's static/ folder.
# Run from Pastor-AI-main (or anywhere — paths are resolved from this script).
#
# Prerequisites: Flutter SDK on PATH
# Usage:
#   .\deploy_flutter_web.ps1

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$FlutterApp = Join-Path $Root "flutter_application_1"
$BuildWeb = Join-Path $FlutterApp "build\web"
$StaticDir = Join-Path $Root "static"

if (-not (Get-Command flutter -ErrorAction SilentlyContinue)) {
    Write-Error "Flutter was not found on PATH. Install Flutter, then re-open your terminal."
}

Push-Location $FlutterApp
try {
    Write-Host "Building Flutter web (base-href=/static/)..."
    flutter pub get
    flutter build web --release --base-href /static/
}
finally {
    Pop-Location
}

if (-not (Test-Path $BuildWeb)) {
    Write-Error "Build output missing: $BuildWeb"
}

Write-Host "Replacing $StaticDir with fresh build..."
if (Test-Path $StaticDir) {
    # Keep the folder, wipe contents so we don't leave stale hashed assets behind.
    Get-ChildItem -Force $StaticDir | Remove-Item -Recurse -Force
} else {
    New-Item -ItemType Directory -Path $StaticDir | Out-Null
}

Copy-Item -Path (Join-Path $BuildWeb "*") -Destination $StaticDir -Recurse -Force

Write-Host ""
Write-Host "Done. Restart Django if it is running:"
Write-Host "  python manage.py runserver"
Write-Host ""
Write-Host "Then hard-refresh the browser (Ctrl+Shift+R)."
Write-Host "If it still looks old, DevTools > Application > Service Workers > Unregister,"
Write-Host "and clear site data for localhost / your ngrok URL."
