#Requires -Version 5.1
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$DeploymentRoot = "",
    [string]$TaskName = "VFREG-VISOR-SOFIA",
    [string]$ExecutableName = "VFREG-VISOR-SOFIA.exe",
    [string]$ConfigName = "config.factory.json",
    [string]$DailyStartTime = "05:50",
    [string]$RunAsUser = "",
    [switch]$NoLogonTrigger,
    [switch]$Remove,
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"

$Script:DailyStartTime = $DailyStartTime
$Script:NoLogonTrigger = [bool]$NoLogonTrigger
$Script:RestartCount = 3
$Script:RestartIntervalMinutes = 1
$Script:MultipleInstancesPolicy = "IgnoreNew"

function Test-VFREGDailyStartTime {
    param([string]$Time)

    if ($Time -notmatch '^([01][0-9]|2[0-3]):([0-5][0-9])$') {
        throw (
            "DailyStartTime must be a valid 24-hour time in HH:mm format " +
            "(for example 05:50 or 23:59). Got: '$Time'."
        )
    }

    return $Time
}

function Resolve-VFREGDeploymentRoot {
    param([string]$RequestedRoot)

    if ($RequestedRoot) {
        return (Resolve-Path -LiteralPath $RequestedRoot).Path
    }

    return (Resolve-Path -LiteralPath (Split-Path -Parent $PSCommandPath)).Path
}

function Test-VFREGDeploymentLayout {
    param(
        [string]$Root,
        [string]$Executable,
        [string]$Config
    )

    $errors = @()
    $exePath = Join-Path $Root $Executable
    $configPath = Join-Path $Root $Config

    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        $errors += "Deployment folder not found: $Root"
    }
    if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) {
        $errors += "Collector executable not found: $exePath"
    }
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        $errors += "Factory configuration not found: $configPath"
    } else {
        try {
            $null = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
        } catch {
            $errors += "Factory configuration is not valid JSON: $configPath ($($_.Exception.Message))"
        }
    }

    return [PSCustomObject]@{
        Root = $Root
        ExecutablePath = $exePath
        ConfigPath = $configPath
        Errors = $errors
    }
}

function Get-VFREGTaskArguments {
    param([string]$ConfigPath)

    return ('--config "{0}" --no-browser' -f $ConfigPath)
}

function New-VFREGScheduledTaskDefinition {
    param(
        [string]$ExecutablePath,
        [string]$Arguments,
        [string]$WorkingDirectory,
        [string]$AccountName,
        [string]$Description
    )

    $action = New-ScheduledTaskAction `
        -Execute $ExecutablePath `
        -Argument $Arguments `
        -WorkingDirectory $WorkingDirectory

    $dailyTrigger = New-ScheduledTaskTrigger -Daily -At $Script:DailyStartTime
    if ($dailyTrigger.PSObject.Properties.Match("StartWhenAvailable").Count -gt 0) {
        $dailyTrigger.StartWhenAvailable = $true
    }
    if ($dailyTrigger.PSObject.Properties.Match("WakeToRun").Count -gt 0) {
        $dailyTrigger.WakeToRun = $true
    }

    $triggers = @($dailyTrigger)
    if (-not $Script:NoLogonTrigger) {
        $logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $AccountName
        if ($logonTrigger.PSObject.Properties.Match("StartWhenAvailable").Count -gt 0) {
            $logonTrigger.StartWhenAvailable = $true
        }
        $triggers += $logonTrigger
    }

    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -WakeToRun `
        -MultipleInstances $Script:MultipleInstancesPolicy `
        -RestartCount $Script:RestartCount `
        -RestartInterval (New-TimeSpan -Minutes $Script:RestartIntervalMinutes) `
        -ExecutionTimeLimit ([TimeSpan]::Zero)

    $principal = New-ScheduledTaskPrincipal `
        -UserId $AccountName `
        -LogonType Interactive `
        -RunLevel Limited

    $task = New-ScheduledTask `
        -Action $action `
        -Trigger $triggers `
        -Settings $settings `
        -Principal $principal `
        -Description $Description

    return [PSCustomObject]@{
        Task = $task
        Action = $action
        Triggers = $triggers
        Settings = $settings
        Principal = $principal
        Arguments = $Arguments
        AccountName = $AccountName
    }
}

function Write-VFREGTaskValidationReport {
    param(
        [pscustomobject]$Layout,
        [pscustomobject]$Definition,
        [string]$TaskName
    )

    $report = [ordered]@{
        mode = "validate"
        task_name = $TaskName
        deployment_root = $Layout.Root
        executable = $Layout.ExecutablePath
        config = $Layout.ConfigPath
        arguments = $Definition.Arguments
        account = $Definition.AccountName
        daily_start = $Script:DailyStartTime
        logon_trigger = -not $Script:NoLogonTrigger
        start_when_available = $true
        wake_to_run = $true
        multiple_instances = $Script:MultipleInstancesPolicy
        restart_count = $Script:RestartCount
        restart_interval_minutes = $Script:RestartIntervalMinutes
        principal_logon_type = "Interactive"
        principal_run_level = "Limited"
    }

    $report | ConvertTo-Json -Compress
}

function Remove-VFREGScheduledTask {
    param([string]$Name)

    $existing = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Host "Scheduled task '$Name' is not registered."
        return
    }

    if ($PSCmdlet.ShouldProcess($Name, "Remove scheduled task")) {
        Unregister-ScheduledTask -TaskName $Name -Confirm:$false
        Write-Host "Removed scheduled task '$Name'."
    }
}

function Install-VFREGScheduledTask {
    param(
        [string]$Name,
        [pscustomobject]$Definition
    )

    if ($PSCmdlet.ShouldProcess($Name, "Register or update scheduled task")) {
        try {
            Register-ScheduledTask `
                -TaskName $Name `
                -InputObject $Definition.Task `
                -Force | Out-Null
        } catch {
            if ($_.Exception.Message -match "Access is denied|Acceso denegado|0x80070005") {
                throw (
                    "Windows denied task registration for account '$($Definition.AccountName)'. " +
                    "Register the task while signed in as that dedicated operator account, or ask IT " +
                    "to grant permission to create tasks for this user. Administrator rights are " +
                    "normally not required when the task runs as the current signed-in user."
                )
            }
            throw
        }

        Write-Host "Registered scheduled task '$Name' for $($Definition.AccountName)."
        Write-Host "Daily start: $($Script:DailyStartTime). Logon trigger: enabled."
        Write-Host "Executable: $($Definition.Action.Execute)"
        Write-Host "Arguments: $($Definition.Arguments)"
    }
}

try {
    if ($ValidateOnly -and $Remove) {
        throw (
            "-ValidateOnly cannot be combined with -Remove. Run -Remove alone to " +
            "unregister the task, or -ValidateOnly alone to inspect the planned registration."
        )
    }

    if (-not $Remove) {
        $Script:DailyStartTime = Test-VFREGDailyStartTime -Time $DailyStartTime
    }

    $deploymentRoot = Resolve-VFREGDeploymentRoot -RequestedRoot $DeploymentRoot
    $accountName = if ($RunAsUser) { $RunAsUser } else { "$env:USERDOMAIN\$env:USERNAME" }

    if ($Remove) {
        Remove-VFREGScheduledTask -Name $TaskName
        exit 0
    }

    $layout = Test-VFREGDeploymentLayout `
        -Root $deploymentRoot `
        -Executable $ExecutableName `
        -Config $ConfigName

    if ($layout.Errors.Count -gt 0) {
        foreach ($item in $layout.Errors) {
            Write-Error $item
        }
        exit 2
    }

    $arguments = Get-VFREGTaskArguments -ConfigPath $layout.ConfigPath
    $description = (
        "Starts the portable VFREG collector before production and after operator logon. " +
        "Uses --no-browser so Task Scheduler retries do not open duplicate dashboard tabs."
    )

    $definition = New-VFREGScheduledTaskDefinition `
        -ExecutablePath $layout.ExecutablePath `
        -Arguments $arguments `
        -WorkingDirectory $layout.Root `
        -AccountName $accountName `
        -Description $description

    if ($ValidateOnly) {
        Write-VFREGTaskValidationReport -Layout $layout -Definition $definition -TaskName $TaskName
        exit 0
    }

    Install-VFREGScheduledTask -Name $TaskName -Definition $definition
    exit 0
} catch {
    Write-Error $_.Exception.Message
    exit 1
}
