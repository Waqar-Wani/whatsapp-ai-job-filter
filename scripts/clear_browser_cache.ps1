[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$SessionDir,
    [switch]$FullReset,
    [switch]$LogoutReset
)

$ErrorActionPreference = "Stop"

function Remove-DirectoryContents {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    if ($PSCmdlet.ShouldProcess($Path, "Remove directory contents")) {
        Get-ChildItem -LiteralPath $Path -Force | Remove-Item -Recurse -Force -ErrorAction Stop
    }
}

function Remove-PathIfExists {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [System.Collections.Generic.List[string]]$Removed,
        [System.Collections.Generic.List[string]]$Locked
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    try {
        if ($PSCmdlet.ShouldProcess($Path, "Remove path")) {
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
            $Removed.Add($Path)
        }
    } catch {
        $Locked.Add($Path)
    }
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $SessionDir) {
    $SessionDir = Join-Path $scriptRoot "..\data\whatsapp_session"
}

$resolvedSessionDir = [System.IO.Path]::GetFullPath($SessionDir)

if (-not (Test-Path -LiteralPath $resolvedSessionDir)) {
    Write-Error "Session directory not found: $resolvedSessionDir"
}

if ($FullReset -and $LogoutReset) {
    Write-Error "Use either -FullReset or -LogoutReset, not both."
}

$cachePaths = @(
    "Cache",
    "Code Cache",
    "GPUCache",
    "DawnCache",
    "GrShaderCache",
    "GraphiteDawnCache",
    "Default\Cache",
    "Default\Code Cache",
    "Default\GPUCache",
    "Default\Service Worker\CacheStorage"
)

$removed = New-Object System.Collections.Generic.List[string]
$locked = New-Object System.Collections.Generic.List[string]

foreach ($relativePath in $cachePaths) {
    $targetPath = Join-Path $resolvedSessionDir $relativePath
    if (Test-Path -LiteralPath $targetPath) {
        Remove-PathIfExists -Path $targetPath -Removed $removed -Locked $locked
    }
}

if ($FullReset) {
    $storagePaths = @(
        "Default\Service Worker\Database",
        "Default\Service Worker\ScriptCache",
        "Default\Session Storage",
        "Default\Storage"
    )

    foreach ($relativePath in $storagePaths) {
        $targetPath = Join-Path $resolvedSessionDir $relativePath
        if (Test-Path -LiteralPath $targetPath) {
            Remove-PathIfExists -Path $targetPath -Removed $removed -Locked $locked
        }
    }
}

if ($LogoutReset) {
    try {
        Remove-DirectoryContents -Path $resolvedSessionDir
        $removed.Add("$resolvedSessionDir\*")
    } catch {
        $locked.Add("$resolvedSessionDir\*")
    }
}

Write-Host "Browser session cleanup complete."
Write-Host "Session directory: $resolvedSessionDir"

if ($removed.Count -eq 0) {
    Write-Host "Nothing was removed."
} else {
    Write-Host "Removed paths:"
    foreach ($path in $removed) {
        Write-Host " - $path"
    }
}

if ($locked.Count -gt 0) {
    Write-Warning "Some paths could not be removed because they appear to be in use:"
    foreach ($path in $locked) {
        Write-Host " - $path"
    }
    Write-Host "Close the browser or Playwright session using this profile and run the script again for a full cleanup."
}

if ($FullReset) {
    Write-Host "Full reset mode also cleared additional storage directories."
} elseif ($LogoutReset) {
    Write-Host "Logout reset mode cleared the full browser profile. WhatsApp Web will require login again."
} else {
    Write-Host "Default mode preserved cookies and login/session storage."
}
