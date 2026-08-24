[CmdletBinding()]
param(
    [string]$PythonPath = "",
    [string]$DistRoot = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot

if (-not $PythonPath) {
    $candidates = @((Join-Path $projectRoot ".venv\Scripts\python.exe"))
    $PythonPath = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}

if (-not $PythonPath -or -not (Test-Path -LiteralPath $PythonPath)) {
    throw "The locked uv environment was not found. Run 'uv sync --locked' first, or pass -PythonPath."
}

& $PythonPath -m PyInstaller --version | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is not installed. Install the portable build dependencies first."
}

if (-not $DistRoot) {
    $DistRoot = Join-Path $projectRoot "portable-dist"
} elseif (-not [System.IO.Path]::IsPathRooted($DistRoot)) {
    $DistRoot = Join-Path $projectRoot $DistRoot
}
$workRoot = Join-Path $projectRoot "build\portable-work"
$specRoot = Join-Path $projectRoot "build\portable-spec"
$dashboardSource = Join-Path $projectRoot "dashboard"
New-Item -ItemType Directory -Force -Path $DistRoot, $workRoot, $specRoot | Out-Null

& $PythonPath -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --console `
    --name "VFREG-VISOR-SOFIA" `
    --distpath $DistRoot `
    --workpath $workRoot `
    --specpath $specRoot `
    --paths $projectRoot `
    --add-data "${dashboardSource}:dashboard" `
    --hidden-import "openpyxl" `
    "app.py"

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE."
}

$packageRoot = Join-Path $DistRoot "VFREG-VISOR-SOFIA"
Copy-Item -LiteralPath (Join-Path $projectRoot "config.factory.json") -Destination $packageRoot -Force
Copy-Item -LiteralPath (Join-Path $projectRoot "portable\Start VFREG Visor.bat") -Destination $packageRoot -Force
Copy-Item -LiteralPath (Join-Path $projectRoot "portable\LEEME-EMPRESA.txt") -Destination $packageRoot -Force
New-Item -ItemType Directory -Force -Path (Join-Path $packageRoot "data\factory") | Out-Null

$executable = Join-Path $packageRoot "VFREG-VISOR-SOFIA.exe"
$hash = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash
@(
    "VFREG-VISOR-SOFIA.exe"
    "SHA256: $hash"
) | Set-Content -LiteralPath (Join-Path $packageRoot "SHA256.txt") -Encoding utf8

$zipPath = Join-Path $DistRoot "VFREG-VISOR-SOFIA.zip"
if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
Compress-Archive -LiteralPath $packageRoot -DestinationPath $zipPath -CompressionLevel Optimal

Write-Host "Portable folder: $packageRoot"
Write-Host "Transfer ZIP:    $zipPath"
