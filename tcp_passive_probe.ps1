param(
    [string]$DeviceAddress = "192.168.1.7",
    [int]$Port = 502,
    [int]$DurationSeconds = 60
)

$ErrorActionPreference = "Stop"
if ($DurationSeconds -lt 1 -or $DurationSeconds -gt 3600) {
    throw "DurationSeconds must be between 1 and 3600"
}

$dataDirectory = Join-Path $PSScriptRoot "data"
[System.IO.Directory]::CreateDirectory($dataDirectory) | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$outputPath = Join-Path $dataDirectory "vfreg-passive-$timestamp.bin"

$client = [System.Net.Sockets.TcpClient]::new()
$stream = $null
$memory = [System.IO.MemoryStream]::new()
$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

try {
    $client.Connect($DeviceAddress, $Port)
    $stream = $client.GetStream()
    Write-Output "Connected to ${DeviceAddress}:${Port}"
    Write-Output "Listening for $DurationSeconds seconds; sending zero application bytes."

    [byte[]]$buffer = [byte[]]::new(4096)
    while ($stopwatch.Elapsed.TotalSeconds -lt $DurationSeconds) {
        if (-not $stream.DataAvailable) {
            Start-Sleep -Milliseconds 100
            continue
        }

        $count = $stream.Read($buffer, 0, $buffer.Length)
        if ($count -eq 0) {
            Write-Output "The remote device closed the connection."
            break
        }

        $memory.Write($buffer, 0, $count)
        [byte[]]$chunk = $buffer[0..($count - 1)]
        $hex = [BitConverter]::ToString($chunk)
        $asciiCharacters = foreach ($value in $chunk) {
            if ($value -ge 32 -and $value -le 126) { [char]$value } else { "." }
        }
        $ascii = $asciiCharacters -join ""
        Write-Output ("[{0:HH:mm:ss.fff}] {1} bytes HEX={2} ASCII={3}" -f (Get-Date), $count, $hex, $ascii)
    }

    [byte[]]$allBytes = $memory.ToArray()
    [System.IO.File]::WriteAllBytes($outputPath, $allBytes)
    Write-Output "Total received: $($allBytes.Length) bytes"
    Write-Output "Evidence file: $outputPath"
}
catch {
    Write-Output "ERROR: $($_.Exception.Message)"
}
finally {
    $stopwatch.Stop()
    if ($stream) { $stream.Dispose() }
    $client.Dispose()
    $memory.Dispose()
}
