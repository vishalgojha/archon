param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$InstallerArgs
)

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

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$installer = Join-Path $repoRoot "tools\install_archon.py"
$candidate = Get-ArchonPythonCandidate

if ($candidate) {
    & $candidate.Exe @($candidate.Args + @($installer) + $InstallerArgs)
    exit $LASTEXITCODE
}

Write-Error "Python 3.11+ was not found. Install Python and the py launcher, then re-run install.ps1."
exit 1
