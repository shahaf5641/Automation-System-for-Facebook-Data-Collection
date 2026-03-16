Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

param(
    [string]$AppName = "FacebookDataExtractor",
    [switch]$OneFile
)

function Get-PythonExe {
    $candidates = @(
        ".\venv\Scripts\python.exe",
        ".\.venv\Scripts\python.exe",
        "python"
    )
    foreach ($candidate in $candidates) {
        if ($candidate -eq "python") {
            try {
                & $candidate --version | Out-Null
                return $candidate
            } catch {
                continue
            }
        } elseif (Test-Path $candidate) {
            return $candidate
        }
    }
    throw "Python was not found. Install Python or create a venv in .\venv."
}

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$pythonExe = Get-PythonExe

Write-Host "Using Python: $pythonExe"
Write-Host "Installing/validating dependencies..."
& $pythonExe -m pip install -r .\requirements.txt
& $pythonExe -m pip install pyinstaller

Write-Host "Cleaning old build artifacts..."
if (Test-Path ".\build") { Remove-Item ".\build" -Recurse -Force }
if (Test-Path ".\dist") { Remove-Item ".\dist" -Recurse -Force }

$pyinstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", $AppName,
    ".\main.py"
)

if ($OneFile) {
    $pyinstallerArgs = @("--onefile") + $pyinstallerArgs
} else {
    $pyinstallerArgs = @("--onedir") + $pyinstallerArgs
}

Write-Host "Building app with PyInstaller..."
& $pythonExe -m PyInstaller @pyinstallerArgs

$timestamp = Get-Date -Format "yyyyMMdd-HHmm"
$releaseDir = Join-Path ".\release" "$AppName-$timestamp"
New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null

if ($OneFile) {
    Copy-Item ".\dist\$AppName.exe" -Destination $releaseDir -Force
} else {
    Copy-Item ".\dist\$AppName" -Destination $releaseDir -Recurse -Force
}

Copy-Item ".\CLIENT_README.md" -Destination $releaseDir -Force

$runBat = @"
@echo off
setlocal
cd /d %~dp0
if exist ".\$AppName.exe" (
  start "" ".\$AppName.exe"
  exit /b 0
)
if exist ".\$AppName\$AppName.exe" (
  start "" ".\$AppName\$AppName.exe"
  exit /b 0
)
echo Could not find $AppName executable.
pause
"@
Set-Content -Path (Join-Path $releaseDir "Run-App.bat") -Value $runBat -Encoding ASCII

Write-Host ""
Write-Host "Build completed successfully."
Write-Host "Release package: $releaseDir"
if ($OneFile) {
    Write-Host "Mode: onefile"
} else {
    Write-Host "Mode: onedir (recommended)"
}
