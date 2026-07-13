# Rebuild the Flutter web app and copy it into Django's static/ folder.
# Run from Pastor-AI-main:
#   .\deploy_flutter_web.ps1
#
# If flutter is not on PATH yet:
#   .\install_flutter_windows.ps1
#   .\deploy_flutter_web.ps1
#
# Or point at an existing SDK (nested zip extract is fine):
#   .\deploy_flutter_web.ps1 -FlutterRoot "C:\src\flutter\flutter"

param(
    [string]$FlutterRoot = $(if ($env:FLUTTER_ROOT) { $env:FLUTTER_ROOT } else { "C:\src\flutter\flutter" })
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$FlutterApp = Join-Path $Root "flutter_application_1"
$BuildWeb = Join-Path $FlutterApp "build\web"
$StaticDir = Join-Path $Root "static"

function Find-FlutterBat {
    param([string]$PreferredRoot)

    $cmd = Get-Command flutter -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { return $cmd.Source }

    $candidates = @(
        $(if ($PreferredRoot) { Join-Path $PreferredRoot "bin\flutter.bat" } else { $null }),
        $(if ($PreferredRoot) { Join-Path $PreferredRoot "flutter\bin\flutter.bat" } else { $null }),
        $(if ($env:FLUTTER_ROOT) { Join-Path $env:FLUTTER_ROOT "bin\flutter.bat" } else { $null }),
        "C:\src\flutter\flutter\bin\flutter.bat",
        "C:\src\flutter\bin\flutter.bat",
        "C:\srs\flutter\flutter\bin\flutter.bat",
        "C:\srs\flutter\bin\flutter.bat",
        (Join-Path $env:USERPROFILE "develop\flutter\bin\flutter.bat"),
        (Join-Path $env:USERPROFILE "flutter\bin\flutter.bat"),
        "C:\flutter\bin\flutter.bat",
        "C:\tools\flutter\bin\flutter.bat"
    ) | Where-Object { $_ }

    foreach ($path in $candidates) {
        if (Test-Path $path) { return (Resolve-Path $path).Path }
    }
    return $null
}

$FlutterBat = Find-FlutterBat -PreferredRoot $FlutterRoot
if (-not $FlutterBat) {
    Write-Host @"

Flutter was not found ('flutter' is not recognized).

If your bat is at C:\src\flutter\flutter\bin\flutter.bat, use that SDK root:
  .\install_flutter_windows.ps1 -FlutterRoot "C:\src\flutter\flutter"
  .\deploy_flutter_web.ps1 -FlutterRoot "C:\src\flutter\flutter"

Or call it directly:
  & C:\src\flutter\flutter\bin\flutter.bat --version

"@
    exit 1
}

Write-Host "Using Flutter: $FlutterBat"

Push-Location $FlutterApp
try {
    Write-Host "Building Flutter web (base-href=/static/)..."
    & $FlutterBat pub get
    if ($LASTEXITCODE -ne 0) { throw "flutter pub get failed" }
    & $FlutterBat build web --release --base-href /static/
    if ($LASTEXITCODE -ne 0) { throw "flutter build web failed" }
}
finally {
    Pop-Location
}

if (-not (Test-Path $BuildWeb)) {
    Write-Error "Build output missing: $BuildWeb"
}

Write-Host "Replacing $StaticDir with fresh build..."
if (Test-Path $StaticDir) {
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
