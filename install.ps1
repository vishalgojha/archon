param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$InstallerArgs
)

function Complete-ArchonInstall {
    param(
        [int]$ExitCode
    )

    $global:LASTEXITCODE = $ExitCode
    if ($env:ARCHON_INSTALL_VIA_CMD -eq "1") {
        exit $ExitCode
    }
    return
}

function Get-ArchonPythonCandidate {
    $candidates = [System.Collections.Generic.List[object]]::new()

    $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCommand) {
        $candidates.Add([pscustomobject]@{ Exe = $pyCommand.Source; Args = @("-3") })
    }

    foreach ($pythonCommand in @(Get-Command python -All -ErrorAction SilentlyContinue)) {
        $candidates.Add([pscustomobject]@{ Exe = $pythonCommand.Source; Args = @() })
    }

    foreach ($pattern in @(
        "$env:LOCALAPPDATA\\Python\\pythoncore-*\\python.exe",
        "$env:LOCALAPPDATA\\Programs\\Python\\Python*\\python.exe",
        "$env:ProgramFiles\\Python*\\python.exe"
    )) {
        foreach ($match in @(Get-ChildItem -Path $pattern -File -ErrorAction SilentlyContinue)) {
            $candidates.Add([pscustomobject]@{ Exe = $match.FullName; Args = @() })
        }
    }

    $seen = @{}
    foreach ($candidate in $candidates) {
        $signature = "{0}|{1}" -f $candidate.Exe, ($candidate.Args -join " ")
        if ($seen.ContainsKey($signature)) {
            continue
        }
        $seen[$signature] = $true
        try {
            & $candidate.Exe @($candidate.Args + @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)")) *> $null
            if ($LASTEXITCODE -eq 0) {
                return $candidate
            }
        }
        catch {
            continue
        }
    }

    return $null
}

function Test-ArchonInstallerFlag {
    param(
        [string[]]$Args,
        [string]$Name
    )

    foreach ($arg in @($Args)) {
        if ($arg -eq $Name -or $arg.StartsWith("$Name=")) {
            return $true
        }
    }
    return $false
}

function Get-ArchonInstallRoot {
    param(
        [string[]]$Args
    )

    for ($idx = 0; $idx -lt @($Args).Count; $idx++) {
        $arg = $Args[$idx]
        if ($arg -eq "--home" -and ($idx + 1) -lt @($Args).Count) {
            return $Args[$idx + 1]
        }
        if ($arg.StartsWith("--home=")) {
            return $arg.Substring("--home=".Length)
        }
    }

    if ($env:LOCALAPPDATA) {
        return (Join-Path $env:LOCALAPPDATA "Programs\Archon")
    }
    return (Join-Path $HOME "AppData\Local\Programs\Archon")
}

function Update-ArchonCurrentSession {
    param(
        [string[]]$Args
    )

    if (Test-ArchonInstallerFlag -Args $Args -Name "--skip-path") {
        return
    }

    if ($env:ARCHON_INSTALL_VIA_CMD -eq "1") {
        Write-Host ""
        Write-Host "PowerShell note: .\install.cmd cannot update the current shell session."
        Write-Host "For immediate activation next time, run: .\install.ps1"
        return
    }

    $installRoot = Get-ArchonInstallRoot -Args $Args
    $binDir = Join-Path $installRoot "bin"
    $archonCmd = Join-Path $binDir "archon.cmd"
    $archonServerCmd = Join-Path $binDir "archon-server.cmd"

    if (-not (Test-Path $archonCmd)) {
        return
    }

    $normalizedBinDir = $binDir.Trim().TrimEnd("\")
    $currentEntries = @($env:PATH -split ";" | Where-Object { $_.Trim() -ne "" })
    $filteredEntries = @(
        $currentEntries | Where-Object { $_.Trim().TrimEnd("\") -ine $normalizedBinDir }
    )
    if ($filteredEntries.Count -gt 0) {
        $env:PATH = "$binDir;$($filteredEntries -join ';')"
    }
    else {
        $env:PATH = $binDir
    }

    Set-Alias -Name archon -Value $archonCmd -Scope Global -Option AllScope -Force
    if (Test-Path $archonServerCmd) {
        Set-Alias -Name archon-server -Value $archonServerCmd -Scope Global -Option AllScope -Force
    }

    Write-Host ""
    Write-Host "Current PowerShell session updated."
    Write-Host "  archon now resolves to: $archonCmd"
    Write-Host "  Try now: archon version"
}

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$installer = Join-Path $repoRoot "tools\install_archon.py"
$candidate = Get-ArchonPythonCandidate

if ($candidate) {
    & $candidate.Exe @($candidate.Args + @($installer) + $InstallerArgs)
    $exitCode = $LASTEXITCODE
    if ($exitCode -eq 0) {
        Update-ArchonCurrentSession -Args $InstallerArgs
    }
    Complete-ArchonInstall -ExitCode $exitCode
    return
}

Write-Error "Python 3.11+ was not found. Install Python and the py launcher, then re-run install.ps1."
Complete-ArchonInstall -ExitCode 1
return
