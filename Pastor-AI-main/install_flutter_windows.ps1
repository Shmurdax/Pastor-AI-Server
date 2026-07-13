# Install Flutter on Windows, add it to PATH, and refresh THIS PowerShell session.
# Run in PowerShell (no admin required):
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
#   .\install_flutter_windows.ps1
#
# Optional:
#   .\install_flutter_windows.ps1 -InstallDir "C:\src"

param(
    [string]$InstallDir = (Join-Path $env:USERPROFILE "develop")
)

$ErrorActionPreference = "Stop"

function Find-FlutterBat {
    param([string[]]$Roots)
    foreach ($root in $Roots) {
        if (-not $root) { continue }
        $candidate = Join-Path $root "bin\flutter.bat"
        if (Test-Path $candidate) { return (Resolve-Path $candidate).Path }
        $nested = Join-Path $root "flutter\bin\flutter.bat"
        if (Test-Path $nested) { return (Resolve-Path $nested).Path }
    }
    return $null
}

function Refresh-SessionPath {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = @($machine, $user) -join ";"
}

function Ensure-UserPathEntry {
    param([Parameter(Mandatory = $true)][string]$Entry)
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not $userPath) { $userPath = "" }
    $parts = $userPath.Split(";", [System.StringSplitOptions]::RemoveEmptyEntries)
    $exists = $parts | Where-Object { $_.TrimEnd("\") -ieq $Entry.TrimEnd("\") }
    if (-not $exists) {
        $newPath = if ([string]::IsNullOrWhiteSpace($userPath)) { $Entry } else { "$userPath;$Entry" }
        [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
        Write-Host "Added to User PATH: $Entry"
    } else {
        Write-Host "Already on User PATH: $Entry"
    }
    Refresh-SessionPath
    if (-not ($env:Path.Split(";") | Where-Object { $_.TrimEnd("\") -ieq $Entry.TrimEnd("\") })) {
        $env:Path = "$Entry;$env:Path"
    }
}

Write-Host "Looking for an existing Flutter SDK..."
$searchRoots = @(
    $env:FLUTTER_ROOT,
    (Join-Path $InstallDir "flutter"),
    $InstallDir,
    (Join-Path $env:USERPROFILE "develop\flutter"),
    (Join-Path $env:USERPROFILE "flutter"),
    "C:\src\flutter",
    "C:\flutter",
    "C:\tools\flutter"
)

$flutterBat = Find-FlutterBat -Roots $searchRoots

if (-not $flutterBat) {
    Write-Host "No Flutter SDK found. Downloading latest stable Windows build..."
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

    $releasesUrl = "https://storage.googleapis.com/flutter_infra_release/releases/releases_windows.json"
    $releases = Invoke-RestMethod -Uri $releasesUrl
    $hash = $releases.current_release.stable
    $rel = $releases.releases | Where-Object { $_.hash -eq $hash } | Select-Object -First 1
    if (-not $rel) {
        throw "Could not resolve the current stable Flutter release."
    }

    $zipName = Split-Path $rel.archive -Leaf
    $zipPath = Join-Path $env:TEMP $zipName
    $downloadUrl = "https://storage.googleapis.com/flutter_infra_release/releases/$($rel.archive)"

    Write-Host "Version: $($rel.version)"
    Write-Host "Downloading:"
    Write-Host "  $downloadUrl"
    Write-Host "This is ~1GB and can take several minutes..."

    # Prefer curl.exe for progress; fall back to Invoke-WebRequest.
    if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
        & curl.exe -L --fail --retry 3 -o $zipPath $downloadUrl
        if ($LASTEXITCODE -ne 0) { throw "Download failed (curl exit $LASTEXITCODE)." }
    } else {
        Invoke-WebRequest -Uri $downloadUrl -OutFile $zipPath
    }

    $targetFlutter = Join-Path $InstallDir "flutter"
    if (Test-Path $targetFlutter) {
        Write-Host "Removing incomplete/old folder: $targetFlutter"
        Remove-Item -Recurse -Force $targetFlutter
    }

    Write-Host "Extracting to $InstallDir ..."
    Expand-Archive -Path $zipPath -DestinationPath $InstallDir -Force
    Remove-Item -Force $zipPath -ErrorAction SilentlyContinue

    $flutterBat = Find-FlutterBat -Roots @($targetFlutter)
    if (-not $flutterBat) {
        throw "Extracted Flutter, but flutter.bat was not found under $targetFlutter"
    }
} else {
    Write-Host "Found Flutter at: $flutterBat"
}

$flutterBin = Split-Path -Parent $flutterBat
$flutterRoot = Split-Path -Parent $flutterBin
Ensure-UserPathEntry -Entry $flutterBin
[Environment]::SetEnvironmentVariable("FLUTTER_ROOT", $flutterRoot, "User")
$env:FLUTTER_ROOT = $flutterRoot

Write-Host ""
Write-Host "Verifying flutter in this session..."
& $flutterBat --version
if ($LASTEXITCODE -ne 0) {
    throw "flutter --version failed. Git for Windows is required: https://git-scm.com/download/win"
}

Write-Host ""
Write-Host "Success. In THIS window you can now run:"
Write-Host "  flutter --version"
Write-Host "  .\deploy_flutter_web.ps1"
Write-Host ""
Write-Host "Other already-open terminals/IDEs still need a restart to pick up PATH."
Write-Host "Flutter root: $flutterRoot"
