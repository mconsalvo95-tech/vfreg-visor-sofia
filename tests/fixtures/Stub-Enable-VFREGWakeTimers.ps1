param(
    [string]$DeploymentRoot = "",
    [string]$ExitFile = ""
)

if ($ExitFile) {
    [System.IO.File]::WriteAllText(
        $ExitFile,
        "0",
        [System.Text.UTF8Encoding]::new($false)
    )
}

Write-Output "mock wake timer enable ok"
exit 0
