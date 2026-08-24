[CmdletBinding()]
param(
    [string]$Version = "0.1.0-pilot-success"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$portableDist = Join-Path $projectRoot "portable-dist"
$sourceRoot = Join-Path $portableDist "VFREG-VISOR-SOFIA"

if (-not (Test-Path -LiteralPath $sourceRoot)) {
    throw "Portable build not found. Run build_portable.ps1 first."
}

$folderName = "VFREG-VISOR-SOFIA-$Version-sanitized"
$releaseRoot = Join-Path $portableDist $folderName
$resolvedDist = (Resolve-Path -LiteralPath $portableDist).Path

if (Test-Path -LiteralPath $releaseRoot) {
    $resolvedRelease = (Resolve-Path -LiteralPath $releaseRoot).Path
    if (-not $resolvedRelease.StartsWith("$resolvedDist\")) {
        throw "Unsafe release cleanup target: $resolvedRelease"
    }
    Remove-Item -LiteralPath $resolvedRelease -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null

# Copy the executable runtime without copying the deployment-specific
# configuration or any collected factory data.
Get-ChildItem -LiteralPath $sourceRoot -Force |
    Where-Object { $_.Name -notin @("config.factory.json", "data", "LEEME-EMPRESA.txt") } |
    Copy-Item -Destination $releaseRoot -Recurse -Force

Copy-Item -LiteralPath (Join-Path $projectRoot "config.example.json") `
    -Destination (Join-Path $releaseRoot "config.factory.json") -Force
Copy-Item -LiteralPath (Join-Path $projectRoot "portable\README-SANITIZED.txt") `
    -Destination (Join-Path $releaseRoot "README-FIRST.txt") -Force
New-Item -ItemType Directory -Force -Path (Join-Path $releaseRoot "data\factory") | Out-Null

$releaseConfig = Get-Content -LiteralPath (Join-Path $releaseRoot "config.factory.json") `
    -Raw | ConvertFrom-Json
if ($releaseConfig.factory.expected_device_mac -or
    $releaseConfig.factory.ethernet_module_serial -or
    $releaseConfig.factory.ethernet_module_version) {
    throw "Sanitized release contains a deployment-specific hardware identifier."
}

$zipPath = Join-Path $portableDist "$folderName.zip"
if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
Compress-Archive -LiteralPath $releaseRoot -DestinationPath $zipPath -CompressionLevel Optimal

$hash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
$checksumPath = "$zipPath.sha256"
"$hash  $folderName.zip" | Set-Content -LiteralPath $checksumPath -Encoding ascii

Write-Host "Sanitized release: $zipPath"
Write-Host "SHA-256:          $hash"
