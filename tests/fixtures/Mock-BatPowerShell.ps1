param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)

function Get-CommandArgument {
    param([string[]]$InvocationArgs)

    $index = [Array]::IndexOf($InvocationArgs, "-Command")
    if ($index -lt 0 -or $index + 1 -ge $InvocationArgs.Count) {
        throw "Mock-BatPowerShell expected -Command"
    }
    return $InvocationArgs[$index + 1]
}

function Write-MockLaunchCount {
    $counterPath = Join-Path $env:VFREG_DEPLOY_ROOT "mock-launch-count.txt"
    $count = 0
    if (Test-Path -LiteralPath $counterPath) {
        $count = [int](Get-Content -LiteralPath $counterPath -Raw)
    }
    $count++
    [System.IO.File]::WriteAllText(
        $counterPath,
        [string]$count,
        [System.Text.UTF8Encoding]::new($false)
    )
}

function Get-MockElevatedArgumentLine {
    param([string]$CommandText)

    if ($CommandText -notmatch '\$p\s*=\s*Start-Process') {
        throw "Mock-BatPowerShell could not locate elevated Start-Process call"
    }
    $prefix = ($CommandText -split '\$p\s*=\s*Start-Process', 2)[0].TrimEnd(';').Trim()
    Invoke-Expression $prefix
    return $argLine
}

$commandText = Get-CommandArgument -InvocationArgs $Args
$mode = $env:VFREG_BAT_TEST_MODE

Write-MockLaunchCount

if ($mode -eq "inspect_args") {
    $argLine = Get-MockElevatedArgumentLine -CommandText $commandText
    $inspectPath = Join-Path $env:VFREG_DEPLOY_ROOT "mock-elevated-argline.txt"
    [System.IO.File]::WriteAllText(
        $inspectPath,
        $argLine,
        [System.Text.UTF8Encoding]::new($false)
    )
    if ($env:VFREG_WAKE_EXITFILE) {
        [System.IO.File]::WriteAllText(
            $env:VFREG_WAKE_EXITFILE,
            "0",
            [System.Text.UTF8Encoding]::new($false)
        )
    }
    exit 0
}

if ($mode -eq "cancel") {
    exit 1223
}

if ($mode -eq "missing_sentinel") {
    exit -196608
}

$scriptPath = $env:VFREG_WAKE_SCRIPT
if (-not $scriptPath -or -not (Test-Path -LiteralPath $scriptPath)) {
    exit 2
}

$invokeArgs = @(
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    $scriptPath,
    "-DeploymentRoot",
    $env:VFREG_DEPLOY_ROOT,
    "-ExitFile",
    $env:VFREG_WAKE_EXITFILE
)
$innerPs = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
& $innerPs @invokeArgs | Out-Null
$innerExit = $LASTEXITCODE

if ($mode -eq "fail") {
    if ($env:VFREG_WAKE_EXITFILE) {
        [System.IO.File]::WriteAllText(
            $env:VFREG_WAKE_EXITFILE,
            "9",
            [System.Text.UTF8Encoding]::new($false)
        )
    }
    exit -196608
}

if ($mode -eq "bad_exit_ok") {
    exit -196608
}

exit $innerExit
