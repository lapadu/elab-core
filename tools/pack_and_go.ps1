# pack_and_go.ps1 - Packages the E-Lab project for deployment on a webserver.
# Only includes the server, built workbench frontend, and non-commercial clients_core.

param(
    [Parameter(Mandatory=$true)]
    [string]$OutputDir,
    [string]$AppBase = '/'
)

$ErrorActionPreference = 'Stop'

# Resolve paths
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$OutputDir = if ([System.IO.Path]::IsPathRooted($OutputDir)) { $OutputDir } else { [System.IO.Path]::GetFullPath((Join-Path $projectRoot $OutputDir)) }

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "  E-Lab Packaging (pack_and_go) - Start" -ForegroundColor Cyan
Write-Host "  Project Root: $projectRoot" -ForegroundColor DarkCyan
Write-Host "  Output Dir:   $OutputDir" -ForegroundColor DarkCyan
Write-Host "  App Base:     $AppBase" -ForegroundColor DarkCyan
Write-Host "=======================================================" -ForegroundColor Cyan

# 1. Build Frontend
Write-Host "Building React Frontend (elab_workbench)..." -ForegroundColor Cyan
Push-Location (Join-Path $projectRoot "elab_workbench")
try {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw "npm command not found. Please install Node.js."
    }
    
    Write-Host "Running npm install..." -ForegroundColor DarkCyan
    & npm.cmd install --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
    
    Write-Host "Running npm run build..." -ForegroundColor DarkCyan
    $env:VITE_BASE = $AppBase
    & npm.cmd run build
    $env:VITE_BASE = $null
    if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
}
finally {
    Pop-Location
}

# 2. Recreate Output Directory
if (Test-Path $OutputDir) {
    Write-Host "Cleaning existing output directory: $OutputDir" -ForegroundColor Yellow
    Remove-Item -Recurse -Force $OutputDir
}
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

# 3. Helper function to copy files while excluding certain patterns
function Copy-FilteredDirectory {
    param(
        [string]$Source,
        [string]$Destination
    )
    
    if (-not (Test-Path $Source)) { return }
    
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    
    Get-ChildItem -Path $Source -Recurse | ForEach-Object {
        $relPath = $_.FullName.Substring($Source.Length + 1)
        
        # Check if we should exclude this path
        if ($relPath -like "*__pycache__*" -or 
            $relPath -like "*.pyc" -or 
            $relPath -like "*.pyo" -or 
            $relPath -like "*.git*" -or 
            $relPath -like "*.pytest_cache*" -or
            $relPath -like "*node_modules*") {
            return
        }
        
        $destPath = Join-Path $Destination $relPath
        if ($_.PSIsContainer) {
            New-Item -ItemType Directory -Path $destPath -Force | Out-Null
        } else {
            # Ensure parent directory exists
            $parentDir = Split-Path $destPath -Parent
            if (-not (Test-Path $parentDir)) {
                New-Item -ItemType Directory -Path $parentDir -Force | Out-Null
            }
            Copy-Item -Path $_.FullName -Destination $destPath -Force
        }
    }
}

# 4. Copy Server and configurations
Write-Host "Copying server files..." -ForegroundColor Cyan
$serverFiles = @(
    "server.py",
    "requirements.txt",
    "pyproject.toml",
    "setup.cfg",
    "pytest.ini",
    "pyrightconfig.json",
    "conftest.py"
)

foreach ($file in $serverFiles) {
    $srcFile = Join-Path $projectRoot $file
    if (Test-Path $srcFile) {
        Copy-Item -Path $srcFile -Destination (Join-Path $OutputDir $file) -Force
    }
}

Copy-FilteredDirectory -Source (Join-Path $projectRoot "elab_server") -Destination (Join-Path $OutputDir "elab_server")
Copy-FilteredDirectory -Source (Join-Path $projectRoot "schemas") -Destination (Join-Path $OutputDir "schemas")

# 5. Copy built Frontend dist
Write-Host "Copying built frontend..." -ForegroundColor Cyan
$frontendDistSource = Join-Path $projectRoot "elab_workbench\dist"
$frontendDistDest = Join-Path $OutputDir "elab_workbench\dist"
if (-not (Test-Path $frontendDistSource)) {
    throw "Frontend build folder not found at $frontendDistSource"
}
Copy-FilteredDirectory -Source $frontendDistSource -Destination $frontendDistDest

# 6. Copy non-commercial clients_core
Write-Host "Copying non-commercial clients_core..." -ForegroundColor Cyan
Copy-FilteredDirectory -Source (Join-Path $projectRoot "elab_clients_core") -Destination (Join-Path $OutputDir "elab_clients_core")

Write-Host "=======================================================" -ForegroundColor Green
Write-Host "  Packaging complete! Output is at $OutputDir" -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Green
