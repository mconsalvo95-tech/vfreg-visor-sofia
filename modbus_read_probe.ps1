param(
    [string]$DeviceAddress = "192.168.1.7",
    [int]$Port = 502,
    [int]$TimeoutMilliseconds = 5000
)

$ErrorActionPreference = "Stop"
$client = [System.Net.Sockets.TcpClient]::new()
$client.ReceiveTimeout = $TimeoutMilliseconds
$client.SendTimeout = $TimeoutMilliseconds
$stream = $null
$reader = $null

try {
    $client.Connect($DeviceAddress, $Port)
    $stream = $client.GetStream()

    # Modbus TCP read-only request:
    # transaction 1, protocol 0, slave 1, function 03,
    # starting register 0, quantity 10.
    [byte[]]$request = 0, 1, 0, 0, 0, 6, 1, 3, 0, 0, 0, 10
    $stream.Write($request, 0, $request.Length)
    $stream.Flush()

    $reader = [System.IO.BinaryReader]::new($stream)
    [byte[]]$header = $reader.ReadBytes(7)
    if ($header.Length -ne 7) {
        throw "Incomplete Modbus header: received $($header.Length) of 7 bytes"
    }

    $remaining = (([int]$header[4] -shl 8) + $header[5]) - 1
    if ($remaining -lt 2 -or $remaining -gt 254) {
        throw "Invalid Modbus length: $remaining remaining bytes"
    }

    [byte[]]$body = $reader.ReadBytes($remaining)
    if ($body.Length -ne $remaining) {
        throw "Incomplete Modbus response: received $($body.Length) of $remaining remaining bytes"
    }

    [byte[]]$response = $header + $body
    Write-Output ("Request:  " + [BitConverter]::ToString($request))
    Write-Output ("Response: " + [BitConverter]::ToString($response))

    if ($response[7] -eq 3) {
        $byteCount = [int]$response[8]
        if ($response.Length -lt 9 + $byteCount) {
            throw "Register data is shorter than its declared byte count"
        }
        for ($index = 0; $index -lt [Math]::Floor($byteCount / 2); $index++) {
            $position = 9 + (2 * $index)
            $value = ([int]$response[$position] -shl 8) + $response[$position + 1]
            Write-Output ("Register {0:D2}: {1} (0x{1:X4})" -f $index, $value)
        }
    }
    elseif (($response[7] -band 0x80) -ne 0) {
        Write-Output "Modbus exception code: $($response[8])"
    }
    else {
        Write-Output "Unexpected Modbus function: $($response[7])"
    }
}
catch {
    Write-Output "ERROR: $($_.Exception.Message)"
}
finally {
    if ($reader) {
        $reader.Dispose()
    }
    elseif ($stream) {
        $stream.Dispose()
    }
    $client.Dispose()
}
