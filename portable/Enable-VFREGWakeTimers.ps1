#Requires -Version 5.1
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$DeploymentRoot = "",
    [switch]$ValidateOnly,
    [switch]$Restore,
    [string]$PowerCfgCommand = "powercfg",
    [string]$ExitFile = "",
    [switch]$SkipAdminCheck
)

$ErrorActionPreference = "Stop"

$Script:SubSleepAlias = "SUB_SLEEP"
$Script:RtcWakeAlias = "RTCWAKE"
$Script:TargetAcValue = 1
$Script:BackupFileName = "vfreg-wake-timer-backup.json"
$Script:AuditFileName = "vfreg-wake-timer-audit.jsonl"
$Script:BackupFormatVersion = 1

function Resolve-VFREGDeploymentRoot {
    param([string]$RequestedRoot)

    if ($RequestedRoot) {
        return (Resolve-Path -LiteralPath $RequestedRoot).Path
    }

    return (Resolve-Path -LiteralPath (Split-Path -Parent $PSCommandPath)).Path
}

function Test-VFREGAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-VFREGPowerCfg {
    param([string[]]$Arguments)

    $output = & $PowerCfgCommand @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        $text = ($output | Out-String).Trim()
        throw "powercfg failed (exit $exitCode): $text"
    }

    return ($output | Out-String)
}

function Get-VFREGGuidFromText {
    param([string]$Text)

    if ($Text -match '([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})') {
        return $Matches[1].ToLowerInvariant()
    }

    throw "Could not parse a power scheme GUID from powercfg output."
}

function Get-VFREGActivePowerSchemeGuid {
    $output = Invoke-VFREGPowerCfg -Arguments @("/getactivescheme")
    return Get-VFREGGuidFromText -Text $output
}

function Get-VFREGSettingIndexFromLine {
    param([string]$Line)

    if ($Line -match '0x([0-9a-fA-F]+)') {
        return [int]::Parse($Matches[1], [System.Globalization.NumberStyles]::HexNumber)
    }

    throw "Could not parse setting index from line: $Line"
}

function Get-VFREGRtcWakeValues {
    param([string]$SchemeGuid)

    $output = Invoke-VFREGPowerCfg -Arguments @(
        "/query",
        $SchemeGuid,
        $Script:SubSleepAlias,
        $Script:RtcWakeAlias
    )

    $acValue = $null
    $dcValue = $null
    foreach ($line in ($output -split "`r?`n")) {
        $trimmed = $line.Trim()
        if ($trimmed -notmatch '0x([0-9a-fA-F]+)') {
            continue
        }
        $index = Get-VFREGSettingIndexFromLine -Line $trimmed
        if ($trimmed -match '(?i)(alterna|\bAC\b|\bCA\b|AC Power Setting Index)') {
            $acValue = $index
        } elseif ($trimmed -match '(?i)(continua|\bDC\b|\bCC\b|DC Power Setting Index)') {
            $dcValue = $index
        }
    }

    if ($null -eq $acValue -or $null -eq $dcValue) {
        throw "Could not read RTC wake AC/DC values from powercfg query output."
    }

    return [PSCustomObject]@{
        SchemeGuid = $SchemeGuid
        AcValue = $acValue
        DcValue = $dcValue
    }
}

function Get-VFREGDataDirectory {
    param([string]$Root)

    $dataDir = Join-Path $Root "data"
    if (-not (Test-Path -LiteralPath $dataDir -PathType Container)) {
        New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
    }

    return $dataDir
}

function Get-VFREGBackupPath {
    param([string]$Root)

    return Join-Path $Root "data\$Script:BackupFileName"
}

function Get-VFREGAuditPath {
    param([string]$Root)

    return Join-Path $Root "data\$Script:AuditFileName"
}

function Write-VFREGJsonAtomically {
    param(
        [string]$Path,
        [object]$Payload
    )

    $directory = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
        New-Item -ItemType Directory -Force -Path $directory | Out-Null
    }

    $tempPath = Join-Path $directory ((".{0}.tmp" -f [Guid]::NewGuid().ToString("N")))
    $json = $Payload | ConvertTo-Json -Depth 6 -Compress:$false
    [System.IO.File]::WriteAllText($tempPath, $json, [System.Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $tempPath -Destination $Path -Force
}

function Add-VFREGAuditRecord {
    param(
        [string]$Root,
        [object]$Record
    )

    $auditPath = Get-VFREGAuditPath -Root $Root
    $line = ($Record | ConvertTo-Json -Compress -Depth 6)
    Add-Content -LiteralPath $auditPath -Value $line -Encoding UTF8
}

function New-VFREGWakeTimerBackupRecord {
    param(
        [string]$Root,
        [pscustomobject]$State,
        [int]$NewAcValue,
        [string]$Operation
    )

    return [ordered]@{
        format_version = $Script:BackupFormatVersion
        timestamp = (Get-Date).ToString("o")
        operation = $Operation
        scheme_guid = $State.SchemeGuid
        previous_ac = $State.AcValue
        previous_dc = $State.DcValue
        new_ac = $NewAcValue
        computer = $env:COMPUTERNAME
        user = "$env:USERDOMAIN\$env:USERNAME"
        deployment_root = $Root
    }
}

function Read-VFREGWakeTimerBackup {
    param([string]$Root)

    $backupPath = Get-VFREGBackupPath -Root $Root
    if (-not (Test-Path -LiteralPath $backupPath -PathType Leaf)) {
        throw "Wake-timer backup not found: $backupPath"
    }

    try {
        $payload = Get-Content -LiteralPath $backupPath -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        throw "Wake-timer backup is not valid JSON: $backupPath ($($_.Exception.Message))"
    }

    if ($payload.format_version -ne $Script:BackupFormatVersion) {
        throw (
            "Unsupported wake-timer backup format_version $($payload.format_version). " +
            "Expected $Script:BackupFormatVersion."
        )
    }

    foreach ($field in @("scheme_guid", "previous_ac", "previous_dc")) {
        if (-not ($payload.PSObject.Properties.Name -contains $field)) {
            throw "Wake-timer backup is missing required field '$field'."
        }
    }

    return $payload
}

function Ensure-VFREGPreChangeBackup {
    param(
        [string]$Root,
        [pscustomobject]$State
    )

    $backupPath = Get-VFREGBackupPath -Root $Root
    if (Test-Path -LiteralPath $backupPath -PathType Leaf) {
        return Read-VFREGWakeTimerBackup -Root $Root
    }

    $record = New-VFREGWakeTimerBackupRecord `
        -Root $Root `
        -State $State `
        -NewAcValue $Script:TargetAcValue `
        -Operation "pre_change_backup"

    Write-VFREGJsonAtomically -Path $backupPath -Payload $record
    Add-VFREGAuditRecord -Root $Root -Record $record
    return $record
}

function Set-VFREGAcRtcWakeValue {
    param(
        [string]$SchemeGuid,
        [int]$AcValue
    )

    if ($PSCmdlet.ShouldProcess($SchemeGuid, "Set AC RTC wake timer to $AcValue")) {
        Invoke-VFREGPowerCfg -Arguments @(
            "/setacvalueindex",
            $SchemeGuid,
            $Script:SubSleepAlias,
            $Script:RtcWakeAlias,
            [string]$AcValue
        ) | Out-Null
        Invoke-VFREGPowerCfg -Arguments @("/setactive", $SchemeGuid) | Out-Null
    }
}

function Test-VFREGRtcWakeMutation {
    param(
        [pscustomobject]$Before,
        [pscustomobject]$After,
        [int]$ExpectedAcValue
    )

    if ($After.AcValue -ne $ExpectedAcValue) {
        throw (
            "Verification failed: AC RTC wake is $($After.AcValue) but expected $ExpectedAcValue."
        )
    }

    if ($After.DcValue -ne $Before.DcValue) {
        throw (
            "Verification failed: DC RTC wake changed from $($Before.DcValue) to $($After.DcValue)."
        )
    }
}

function Write-VFREGWakeTimerValidationReport {
    param(
        [string]$Root,
        [pscustomobject]$State,
        [object]$Backup = $null
    )

    $report = [ordered]@{
        mode = "validate"
        deployment_root = $Root
        active_scheme_guid = $State.SchemeGuid
        rtc_wake_ac = $State.AcValue
        rtc_wake_dc = $State.DcValue
        intended_ac = $Script:TargetAcValue
        dc_unchanged = $true
        backup_present = [bool]$Backup
        backup_path = (Get-VFREGBackupPath -Root $Root)
        idempotent = ($State.AcValue -eq $Script:TargetAcValue)
    }

    if ($Backup) {
        $report.backup = [ordered]@{
            timestamp = $Backup.timestamp
            previous_ac = $Backup.previous_ac
            previous_dc = $Backup.previous_dc
        }
    }

    $report | ConvertTo-Json -Compress
}

function Enable-VFREGWakeTimers {
    param(
        [string]$Root,
        [pscustomobject]$State
    )

    $before = $State
    $backup = Ensure-VFREGPreChangeBackup -Root $Root -State $before

    if ($before.AcValue -eq $Script:TargetAcValue) {
        $record = New-VFREGWakeTimerBackupRecord `
            -Root $Root `
            -State $before `
            -NewAcValue $Script:TargetAcValue `
            -Operation "enable_idempotent"
        Add-VFREGAuditRecord -Root $Root -Record $record
        Write-Host "RTC wake timers for AC power are already enabled (value=$($Script:TargetAcValue))."
        return [PSCustomObject]@{
            Changed = $false
            Backup = $backup
            State = $before
        }
    }

    Set-VFREGAcRtcWakeValue -SchemeGuid $before.SchemeGuid -AcValue $Script:TargetAcValue
    $after = Get-VFREGRtcWakeValues -SchemeGuid $before.SchemeGuid
    Test-VFREGRtcWakeMutation -Before $before -After $after -ExpectedAcValue $Script:TargetAcValue

    $record = New-VFREGWakeTimerBackupRecord `
        -Root $Root `
        -State $before `
        -NewAcValue $Script:TargetAcValue `
        -Operation "enable"
    Add-VFREGAuditRecord -Root $Root -Record $record

    Write-Host "Enabled RTC wake timers for AC power (value=$($Script:TargetAcValue))."
    Write-Host "DC/battery setting left unchanged at $($before.DcValue)."
    Write-Host "Backup: $(Get-VFREGBackupPath -Root $Root)"

    return [PSCustomObject]@{
        Changed = $true
        Backup = $backup
        State = $after
    }
}

function Restore-VFREGWakeTimers {
    param(
        [string]$Root,
        [pscustomobject]$State
    )

    $backup = Read-VFREGWakeTimerBackup -Root $Root
    $targetAc = [int]$backup.previous_ac
    $before = $State

    if ($before.SchemeGuid -ne [string]$backup.scheme_guid) {
        throw (
            "Active power scheme $($before.SchemeGuid) does not match backup scheme " +
            "$($backup.scheme_guid). Restore manually or re-run enable on the current scheme."
        )
    }

    if ($before.AcValue -eq $targetAc) {
        $record = New-VFREGWakeTimerBackupRecord `
            -Root $Root `
            -State $before `
            -NewAcValue $targetAc `
            -Operation "restore_idempotent"
        Add-VFREGAuditRecord -Root $Root -Record $record
        Write-Host "AC RTC wake already matches backup value ($targetAc)."
        return [PSCustomObject]@{
            Changed = $false
            Backup = $backup
            State = $before
        }
    }

    Set-VFREGAcRtcWakeValue -SchemeGuid $before.SchemeGuid -AcValue $targetAc
    $after = Get-VFREGRtcWakeValues -SchemeGuid $before.SchemeGuid
    Test-VFREGRtcWakeMutation -Before $before -After $after -ExpectedAcValue $targetAc

    $record = New-VFREGWakeTimerBackupRecord `
        -Root $Root `
        -State $before `
        -NewAcValue $targetAc `
        -Operation "restore"
    Add-VFREGAuditRecord -Root $Root -Record $record

    Write-Host "Restored AC RTC wake to backup value ($targetAc)."
    Write-Host "DC/battery setting left unchanged at $($before.DcValue)."

    return [PSCustomObject]@{
        Changed = $true
        Backup = $backup
        State = $after
    }
}

function Write-VFREGExitCode {
    param([int]$Code)

    if ($ExitFile) {
        [System.IO.File]::WriteAllText($ExitFile, [string]$Code, [System.Text.UTF8Encoding]::new($false))
    }

    exit $Code
}

try {
    if ($ValidateOnly -and $Restore) {
        throw (
            "-ValidateOnly cannot be combined with -Restore. Use -ValidateOnly to inspect " +
            "current values, -Restore alone to revert from backup, or run without switches " +
            "to enable AC wake timers."
        )
    }

    $deploymentRoot = Resolve-VFREGDeploymentRoot -RequestedRoot $DeploymentRoot
    $schemeGuid = Get-VFREGActivePowerSchemeGuid
    $state = Get-VFREGRtcWakeValues -SchemeGuid $schemeGuid
    $backup = $null
    $backupPath = Get-VFREGBackupPath -Root $deploymentRoot
    if (Test-Path -LiteralPath $backupPath -PathType Leaf) {
        $backup = Read-VFREGWakeTimerBackup -Root $deploymentRoot
    }

    if ($ValidateOnly) {
        Write-VFREGWakeTimerValidationReport -Root $deploymentRoot -State $state -Backup $backup
        Write-VFREGExitCode -Code 0
    }

    if (-not ($SkipAdminCheck -or (Test-VFREGAdministrator))) {
        throw (
            "Administrator rights are required to change or restore AC wake timers. " +
            "Run this script elevated, for example via 'Configurar despertar del PC.bat'."
        )
    }

    if ($Restore) {
        Restore-VFREGWakeTimers -Root $deploymentRoot -State $state | Out-Null
        Write-VFREGExitCode -Code 0
    }

    Enable-VFREGWakeTimers -Root $deploymentRoot -State $state | Out-Null
    Write-VFREGExitCode -Code 0
} catch {
    Write-Error $_.Exception.Message
    Write-VFREGExitCode -Code 1
}
