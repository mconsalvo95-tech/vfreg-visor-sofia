param(
    [string]$DeviceAddress = "192.168.1.7",
    [int]$Port = 502,
    [ValidateRange(1, 247)][int]$UnitStart = 1,
    [ValidateRange(1, 247)][int]$UnitEnd = 10,
    [ValidateSet(3, 4)][int]$FunctionCode = 3,
    [ValidateRange(0, 65535)][int]$StartRegister = 0,
    [ValidateRange(1, 125)][int]$Quantity = 1,
    [ValidateRange(250, 5000)][int]$ResponseWaitMilliseconds = 1200,
    [ValidateRange(0, 5000)][int]$DelayMilliseconds = 200,
    [bool]$StopOnResponse = $true
)

$ErrorActionPreference = "Stop"
if ($UnitEnd -lt $UnitStart) {
    throw "UnitEnd must be greater than or equal to UnitStart"
}

$dataDirectory = Join-Path $PSScriptRoot "data"
[System.IO.Directory]::CreateDirectory($dataDirectory) | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$evidencePath = Join-Path $dataDirectory "modbus-discovery-$timestamp.csv"
$results = [System.Collections.Generic.List[object]]::new()

Write-Output "READ-ONLY MODBUS DISCOVERY"
Write-Output "Target: ${DeviceAddress}:${Port}"
Write-Output "Units: $UnitStart-$UnitEnd; function: $FunctionCode; register: $StartRegister; quantity: $Quantity"
Write-Output "No Modbus write function can be sent by this script."

for ($unit = $UnitStart; $unit -le $UnitEnd; $unit++) {
    $client = [System.Net.Sockets.TcpClient]::new()
    $stream = $null
    $status = "NO_RESPONSE"
    $requestHex = ""
    $responseHex = ""
    $detail = ""
    $transaction = $unit

    try {
        $client.ReceiveTimeout = $ResponseWaitMilliseconds
        $client.SendTimeout = $ResponseWaitMilliseconds
        $client.Connect($DeviceAddress, $Port)
        $stream = $client.GetStream()

        [byte[]]$request = @(
            (($transaction -shr 8) -band 0xFF),
            ($transaction -band 0xFF),
            0, 0,
            0, 6,
            $unit,
            $FunctionCode,
            (($StartRegister -shr 8) -band 0xFF),
            ($StartRegister -band 0xFF),
            (($Quantity -shr 8) -band 0xFF),
            ($Quantity -band 0xFF)
        )
        $requestHex = [BitConverter]::ToString($request)
        $stream.Write($request, 0, $request.Length)
        $stream.Flush()

        $wait = [System.Diagnostics.Stopwatch]::StartNew()
        while (-not $stream.DataAvailable -and $wait.ElapsedMilliseconds -lt $ResponseWaitMilliseconds) {
            Start-Sleep -Milliseconds 25
        }
        $wait.Stop()

        if ($stream.DataAvailable) {
            $reader = [System.IO.BinaryReader]::new($stream)
            try {
                [byte[]]$header = $reader.ReadBytes(7)
                if ($header.Length -ne 7) {
                    throw "Incomplete response header ($($header.Length)/7 bytes)"
                }
                $remaining = (([int]$header[4] -shl 8) + $header[5]) - 1
                if ($remaining -lt 2 -or $remaining -gt 254) {
                    throw "Invalid Modbus response length $remaining"
                }
                [byte[]]$body = $reader.ReadBytes($remaining)
                if ($body.Length -ne $remaining) {
                    throw "Incomplete response body ($($body.Length)/$remaining bytes)"
                }
                [byte[]]$response = $header + $body
                $responseHex = [BitConverter]::ToString($response)
                if (($response[7] -band 0x80) -ne 0) {
                    $status = "MODBUS_EXCEPTION"
                    $detail = "Exception code $($response[8])"
                }
                else {
                    $status = "RESPONSE"
                    $detail = "Function $($response[7]); $($response.Length) bytes"
                }
            }
            finally {
                $reader.Dispose()
                $stream = $null
            }
        }
    }
    catch {
        $status = "ERROR"
        $detail = $_.Exception.Message
        if (-not $requestHex) { $requestHex = "" }
    }
    finally {
        if ($stream) { $stream.Dispose() }
        $client.Dispose()
    }

    $record = [pscustomobject]@{
        timestamp = (Get-Date).ToString("o")
        unit_id = $unit
        function_code = $FunctionCode
        start_register = $StartRegister
        quantity = $Quantity
        status = $status
        request_hex = $requestHex
        response_hex = $responseHex
        detail = $detail
    }
    $results.Add($record)
    Write-Output ("Unit {0:D3}: {1}{2}" -f $unit, $status, $(if ($detail) { " - $detail" } else { "" }))

    if ($StopOnResponse -and $status -in @("RESPONSE", "MODBUS_EXCEPTION")) {
        Write-Output "A Modbus slave answered; stopping the scan immediately."
        break
    }
    if ($DelayMilliseconds -gt 0) {
        Start-Sleep -Milliseconds $DelayMilliseconds
    }
}

$results | Export-Csv -Path $evidencePath -NoTypeInformation -Encoding UTF8
Write-Output "Evidence file: $evidencePath"
