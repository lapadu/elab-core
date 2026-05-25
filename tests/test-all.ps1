<#
.SYNOPSIS
    Run complete E-Lab test suite (backend + frontend) with a compact summary.

.DESCRIPTION
    Executes Python tests (pytest) and frontend tests (Vitest) from the
    repository root. The script prints a concise evaluation table and returns a
    non-zero exit code if any selected test phase fails.

.PARAMETER BackendOnly
    Run only backend tests.

.PARAMETER FrontendOnly
    Run only frontend tests.

.PARAMETER NoCoverage
    Disable coverage flags for backend and frontend tests.

.PARAMETER StopOnFail
    Stop immediately after the first failed phase.

.PARAMETER DryRun
    Print commands without executing them.

.EXAMPLE
    .\tests\test-all.ps1

.EXAMPLE
    .\tests\test-all.ps1 -NoCoverage

.EXAMPLE
    .\tests\test-all.ps1 -BackendOnly -StopOnFail
#>
[CmdletBinding()]
param(
    [switch]$BackendOnly,
    [switch]$FrontendOnly,
    [switch]$NoCoverage,
    [switch]$StopOnFail,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path $PSScriptRoot -Parent
$WorkbenchDir = Join-Path $RepoRoot 'elab_workbench'
$ResultsDir = Join-Path $RepoRoot 'test-results'

if ($BackendOnly -and $FrontendOnly) {
    Write-Error 'Use either -BackendOnly or -FrontendOnly, not both.'
    exit 2
}

$RunBackend = -not $FrontendOnly
$RunFrontend = -not $BackendOnly

function Write-Step([string]$Message) {
    Write-Host "`n=== $Message ===" -ForegroundColor Cyan
}

function Write-Info([string]$Message) {
    Write-Host "  $Message" -ForegroundColor DarkGray
}

function Write-Warn([string]$Message) {
    Write-Host "  [WARN] $Message" -ForegroundColor Yellow
}

function New-Result([string]$Name, [bool]$Passed, [int]$ExitCode, [double]$DurationSec, [string]$Command) {
    [PSCustomObject]@{
        Phase       = $Name
        Status      = if ($Passed) { 'PASS' } else { 'FAIL' }
        ExitCode    = $ExitCode
        DurationSec = [Math]::Round($DurationSec, 2)
        Command     = $Command
    }
}

function Invoke-Phase {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$Exe,
        [Parameter(Mandatory = $true)][string[]]$ExeArgs
    )

    $commandLine = "$Exe $($ExeArgs -join ' ')"
    Write-Step $Name
    Write-Info "cwd: $WorkingDirectory"
    Write-Info "cmd: $commandLine"

    if ($DryRun) {
        return New-Result -Name $Name -Passed $true -ExitCode 0 -DurationSec 0 -Command $commandLine
    }

    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $resolvedCommand = Get-Command $Exe -ErrorAction Stop
        $resolvedExe = $resolvedCommand.Source

        # On Windows, npm often resolves to npm.ps1, which is not directly
        # runnable via Start-Process. Prefer sibling npm.cmd when available.
        if ($resolvedCommand.CommandType -eq 'ExternalScript' -and $resolvedExe.EndsWith('.ps1', [System.StringComparison]::OrdinalIgnoreCase)) {
            $cmdVariant = [System.IO.Path]::ChangeExtension($resolvedExe, '.cmd')
            if (Test-Path $cmdVariant) {
                $resolvedExe = $cmdVariant
            }
        }

        $process = Start-Process -FilePath $resolvedExe -ArgumentList $ExeArgs -WorkingDirectory $WorkingDirectory -NoNewWindow -Wait -PassThru
        $exitCode = $process.ExitCode
    } catch {
        $exitCode = 1
        Write-Warn "Command threw an exception: $($_.Exception.Message)"
    } finally {
        $stopwatch.Stop()
    }

    $passed = ($exitCode -eq 0)
    return New-Result -Name $Name -Passed $passed -ExitCode $exitCode -DurationSec $stopwatch.Elapsed.TotalSeconds -Command $commandLine
}

if (-not (Test-Path $ResultsDir)) {
    New-Item -Path $ResultsDir -ItemType Directory | Out-Null
}

$results = @()

if ($RunBackend) {
    $pytestArgs = @('-m', 'pytest')

    if (-not $NoCoverage) {
        $pytestHelp = ''
        try {
            $pytestHelp = (& python -m pytest --help 2>$null | Out-String)
        } catch {
            $pytestHelp = ''
        }

        if ($pytestHelp -match '--cov') {
            $pytestArgs += @(
                '--cov=elab_server',
                '--cov=elab_clients',
                '--cov-report=term-missing',
                "--cov-report=xml:$ResultsDir\coverage-python.xml",
                "--junitxml=$ResultsDir\pytest-junit.xml"
            )
        } else {
            Write-Warn 'pytest-cov not detected, backend tests run without coverage.'
        }
    }

    $backendResult = Invoke-Phase -Name 'Backend Tests (pytest)' -WorkingDirectory $RepoRoot -Exe 'python' -ExeArgs $pytestArgs
    $results += $backendResult

    if ($StopOnFail -and -not $backendResult.Status.Equals('PASS')) {
        Write-Warn 'Stopping on first failure due to -StopOnFail.'
    }
}

if ($RunFrontend -and (-not $StopOnFail -or ($results | Where-Object { $_.Status -eq 'FAIL' }).Count -eq 0)) {
    if (-not (Test-Path (Join-Path $WorkbenchDir 'package.json'))) {
        $frontendResult = New-Result -Name 'Frontend Tests (vitest)' -Passed $false -ExitCode 2 -DurationSec 0 -Command 'npm run test'
        $results += $frontendResult
        Write-Warn "Could not find frontend workspace at: $WorkbenchDir"
    } else {
        $vitestArgs = @('run', 'test')
        if (-not $NoCoverage) {
            $vitestArgs += @('--', '--coverage')
        }

        $frontendResult = Invoke-Phase -Name 'Frontend Tests (vitest)' -WorkingDirectory $WorkbenchDir -Exe 'npm' -ExeArgs $vitestArgs
        $results += $frontendResult
    }
}

Write-Step 'Summary'
$results | Select-Object Phase, Status, ExitCode, DurationSec | Format-Table -AutoSize

$failed = @($results | Where-Object { $_.Status -eq 'FAIL' })

if ($failed.Count -gt 0) {
    Write-Host "`nResult: FAILED ($($failed.Count) phase(s) failed)." -ForegroundColor Red
    exit 1
}

Write-Host "`nResult: SUCCESS (all selected phases passed)." -ForegroundColor Green
exit 0