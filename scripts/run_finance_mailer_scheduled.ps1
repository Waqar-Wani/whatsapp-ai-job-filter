$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ProjectRoot "venv\Scripts\python.exe"
$RunnerScript = Join-Path $ProjectRoot "scripts\run_finance_mailer.py"
$LogFile = Join-Path $ProjectRoot "logs\finance_mailer.log"
$LockFile = Join-Path $ProjectRoot "data\.finance_mailer.lock"

New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "logs") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "data") | Out-Null

if (Test-Path $LockFile) {
    Add-Content -Path $LogFile -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | INFO | SCHEDULER | Skipping finance mailer run because a previous run is still active."
    exit 0
}

try {
    Set-Content -Path $LockFile -Value $PID
    Add-Content -Path $LogFile -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | INFO | SCHEDULER | Starting scheduled finance mailer run"
    & $PythonExe $RunnerScript 2>&1 | Tee-Object -FilePath $LogFile -Append | Out-Host
    $ExitCode = $LASTEXITCODE
    Add-Content -Path $LogFile -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | INFO | SCHEDULER | Completed scheduled finance mailer run with exit code $ExitCode"
    exit $ExitCode
}
catch {
    Add-Content -Path $LogFile -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | ERROR | SCHEDULER | $($_.Exception.Message)"
    throw
}
finally {
    Remove-Item -LiteralPath $LockFile -Force -ErrorAction SilentlyContinue
}
