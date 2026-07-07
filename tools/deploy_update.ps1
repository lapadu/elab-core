# deploy_update.ps1 - Build, tag, and deploy E-Lab to servers
#
# Usage:
#   .\deploy_update.ps1                        # Auto-increment patch (1.0.0 -> 1.0.1), deploy to all servers
#   .\deploy_update.ps1 -Version 2.0.0        # Specific version
#   .\deploy_update.ps1 -DryRun               # Build + tag only, no upload
#   .\deploy_update.ps1 -NoKeepUserdata        # Overwrite user_data on servers
#   .\deploy_update.ps1 -SkipTag              # No git tag; use next patch version with -rc suffix
#   .\deploy_update.ps1 -Rollback             # List archives and rollback interactively
#   .\deploy_update.ps1 -Rollback -RollbackFile "1.0.0_20260513_120000.zip"
#   .\deploy_update.ps1 -SshUser "lapadu"      # Use a specific SSH user (defaults to lapadu)
#   .\deploy_update.ps1 -SshKey "C:\path\id_rsa" # Use a specific SSH private key file
#
param(
    [string]$Version = '',
    [string]$ServerList = 'servers.json',
    [switch]$NoKeepUserdata,
    [switch]$DryRun,
    [switch]$NoPush,
    [switch]$SkipTag,
    [switch]$Rollback,
    [string]$RollbackFile = '',
    [string]$SshUser = 'lapadu',
    [string]$SshKey = ''
)

$ErrorActionPreference = 'Stop'

function Resolve-ProjectRoot {
    param([string]$StartDir)
    $current = Resolve-Path $StartDir
    while ($true) {
        $serverPy = Join-Path $current 'server.py'
        $serverPkg = Join-Path $current 'elab_server'
        if ((Test-Path $serverPy) -and (Test-Path $serverPkg)) {
            return $current
        }
        $parent = Split-Path $current -Parent
        if (-not $parent -or $parent -eq $current) {
            throw 'Projektroot nicht gefunden.'
        }
        $current = $parent
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-ProjectRoot -StartDir $scriptDir
Set-Location $projectRoot

# -- Load server list (needed for both deploy and rollback) ------------
$serverListPath = if ([System.IO.Path]::IsPathRooted($ServerList)) { $ServerList } else { Join-Path $projectRoot $ServerList }
if (-not (Test-Path $serverListPath)) {
    throw "Serverliste nicht gefunden: $serverListPath"
}
$config = Get-Content $serverListPath -Raw | ConvertFrom-Json
$servers = $config.servers

if ($SshKey -and -not (Test-Path $SshKey)) {
    throw "SSH Schluesseldatei nicht gefunden: $SshKey"
}

# ======================================================================
# ROLLBACK MODE
# ======================================================================
if ($Rollback) {
    Write-Host "=======================================================" -ForegroundColor Yellow
    Write-Host "  E-Lab ROLLBACK" -ForegroundColor Yellow
    Write-Host "=======================================================" -ForegroundColor Yellow
    Write-Host ''

    $sshUserPrompt = Read-Host "SSH Benutzername fuer den Raspberry Pi (Standard: '$SshUser')"
    $sshUser = if ([string]::IsNullOrWhiteSpace($sshUserPrompt)) { $SshUser } else { $sshUserPrompt }
    $keepUserdata = if ($NoKeepUserdata) { $false } else { $true }

    foreach ($server in $servers) {
        $baseUrl = "$($server.protocol)://$($server.host)$($server.update_subpath)"

        Write-Host "-------------------------------------------------" -ForegroundColor DarkGray
        Write-Host "Server: $baseUrl" -ForegroundColor Cyan

        $hostParts = $server.host -split ':'
        $targetIp = $hostParts[0]
        $targetPort = if ($hostParts.Count -gt 1) { $hostParts[1] } else { "8000" }
        $localUrl = "http://127.0.0.1:${targetPort}$($server.update_subpath)"

        # Get archive list via SSH
        $curlCmdList = "curl -s '$localUrl/api/update/archives'"
        $sshArgs = @()
        if ($SshKey) {
            $sshArgs += @("-i", $SshKey)
        }
        $sshArgs += @("$sshUser@$targetIp", $curlCmdList)
        $archivesJson = & ssh @sshArgs
        if ($LASTEXITCODE -ne 0 -or -not $archivesJson) {
            Write-Host "  FEHLER beim Abrufen der Archive via SSH auf $targetIp." -ForegroundColor Red
            continue
        }
        
        $archives = $archivesJson | ConvertFrom-Json

        if (-not $archives -or $archives.Count -eq 0) {
            Write-Host "  Keine Archive vorhanden." -ForegroundColor Yellow
            continue
        }

        $selectedFile = $RollbackFile
        if (-not $selectedFile) {
            # Interactive selection
            Write-Host ''
            Write-Host "  Verfuegbare Archive:" -ForegroundColor DarkCyan
            for ($i = 0; $i -lt $archives.Count; $i++) {
                $a = $archives[$i]
                Write-Host "    [$i] $($a.filename)  ($($a.size_mb) MB, $($a.created))"
            }
            Write-Host ''
            $choice = Read-Host "  Nummer waehlen (oder Enter zum Abbrechen)"
            if (-not $choice -or $choice -eq '') {
                Write-Host "  Abgebrochen." -ForegroundColor Yellow
                continue
            }
            $idx = [int]$choice
            if ($idx -lt 0 -or $idx -ge $archives.Count) {
                Write-Host "  Ungueltige Auswahl." -ForegroundColor Red
                continue
            }
            $selectedFile = $archives[$idx].filename
        }

        Write-Host "  Rollback auf: $selectedFile" -ForegroundColor Yellow
        $rollbackBody = @{ filename = $selectedFile; keep_userdata = $keepUserdata } | ConvertTo-Json -Compress
        
        $curlCmdRollback = "echo '$rollbackBody' | curl -s -X POST '$localUrl/api/update/rollback' -H 'Content-Type: application/json' -d @-"
        $sshArgs = @()
        if ($SshKey) {
            $sshArgs += @("-i", $SshKey)
        }
        $sshArgs += @("$sshUser@$targetIp", $curlCmdRollback)
        $rollbackRespJson = & ssh @sshArgs
        
        if ($LASTEXITCODE -eq 0 -and $rollbackRespJson) {
            $rollbackResp = $rollbackRespJson | ConvertFrom-Json
            Write-Host "  Rollback erfolgreich: $($rollbackResp.status)" -ForegroundColor Green
        } else {
            Write-Host "  FEHLER beim Rollback via SSH." -ForegroundColor Red
        }
        Write-Host ''
    }

    Write-Host "=======================================================" -ForegroundColor Yellow
    Write-Host "  Rollback abgeschlossen." -ForegroundColor Yellow
    Write-Host "=======================================================" -ForegroundColor Yellow
    exit 0
}

# ======================================================================
# DEPLOY MODE
# ======================================================================

# -- 1. Determine version ---------------------------------------------
function Get-NextVersion {
    # Try to get the latest tag
    $latestTag = $null
    try {
        $latestTag = git describe --tags --abbrev=0 2>&1 | Out-String
        $latestTag = $latestTag.Trim()
        if ($LASTEXITCODE -ne 0) { $latestTag = $null }
    } catch {
        $latestTag = $null
    }
    if (-not $latestTag) {
        # No tags exist yet - start at 1.0.0
        return '1.0.0'
    }
    # Remove leading 'v' if present
    $tagVersion = $latestTag -replace '^v', ''
    $parts = $tagVersion -split '\.'
    if ($parts.Count -ne 3) {
        throw "Unerwartetes Tag-Format: $latestTag (erwartet: v<major>.<minor>.<patch>)"
    }
    $major = [int]$parts[0]
    $minor = [int]$parts[1]
    $patch = [int]$parts[2] + 1
    return "$major.$minor.$patch"
}

if ($SkipTag) {
    # SkipTag mode: use next patch version with -rc suffix, no git tag
    if (-not $Version) {
        $Version = Get-NextVersion
        $Version = "$Version-rc"
    }
} elseif (-not $Version) {
    $Version = Get-NextVersion
}
# Normalize: strip leading 'v' for internal use
$Version = $Version -replace '^v', ''
$tagName = "v$Version"

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "  E-Lab Deploy - Version $Version" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ''

# -- 2. Git tag ---------------------------------------------------------
if ($SkipTag) {
    Write-Host "SkipTag aktiv - kein Git-Tag wird erstellt." -ForegroundColor Yellow
} else {
    $existingTag = git tag -l $tagName 2>$null
    if ($existingTag) {
        Write-Host "Tag $tagName existiert bereits - ueberspringe Tagging." -ForegroundColor Yellow
    } else {
        Write-Host "Erstelle Git-Tag: $tagName" -ForegroundColor Cyan
        git tag -a $tagName -m "Release $tagName"
        if ($LASTEXITCODE -ne 0) { throw "git tag fehlgeschlagen" }

        if (-not $NoPush) {
            Write-Host "Pushe Tag $tagName ..." -ForegroundColor Cyan
            git push origin $tagName
            if ($LASTEXITCODE -ne 0) {
                Write-Host "WARNUNG: git push origin $tagName fehlgeschlagen (ggf. kein Remote konfiguriert)" -ForegroundColor Yellow
            }
        }
    }
}

# -- 3. Server-Ziele anzeigen ------------------------------------------
Write-Host "Server-Ziele: $($servers.Count)" -ForegroundColor DarkCyan
foreach ($s in $servers) {
    Write-Host "  - $($s.protocol)://$($s.host)$($s.update_subpath)" -ForegroundColor DarkCyan
}
Write-Host ''

# -- 4. Build per unique app_subpath -----------------------------------
# Group servers by app_subpath to avoid redundant builds
$subpathGroups = $servers | Group-Object -Property app_subpath

$buildArtifacts = @{}  # subpath -> zip path

foreach ($group in $subpathGroups) {
    $subpath = $group.Name
    $buildDir = Join-Path $projectRoot "build_${Version}_$($subpath -replace '[/\\]', '_')"

    Write-Host "Baue fuer Subpath '$subpath' ..." -ForegroundColor Cyan
    $env:VITE_APP_VERSION = $Version
    & (Join-Path $scriptDir 'pack_and_go.ps1') -OutputDir $buildDir -AppBase $subpath
    $env:VITE_APP_VERSION = $null
    if ($LASTEXITCODE -ne 0) { throw "tools/pack_and_go.ps1 fehlgeschlagen fuer Subpath '$subpath'" }

    # Create ZIP
    $subpathClean = ($subpath -replace '[/\\]', '_').Trim('_')
    if ([string]::IsNullOrWhiteSpace($subpathClean)) { $subpathClean = 'ELab' }
    $zipName = "${subpathClean}_v${Version}.zip"
    $zipPath = Join-Path $projectRoot $zipName

    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
    Write-Host "Erstelle ZIP: $zipName" -ForegroundColor Cyan
    Compress-Archive -Path "$buildDir\*" -DestinationPath $zipPath -Force

    $buildArtifacts[$subpath] = $zipPath

    # Cleanup build directory
    Remove-Item -Recurse -Force $buildDir
}

Write-Host ''

# -- 5. Deploy to servers (sequentially) ------------------------------
if ($DryRun) {
    Write-Host "DRY RUN - Ueberspringe Upload und Deployment." -ForegroundColor Yellow
    Write-Host "Erstellte ZIPs:"
    foreach ($entry in $buildArtifacts.GetEnumerator()) {
        Write-Host "  [$($entry.Key)] $($entry.Value)"
    }
    Write-Host ''
    Write-Host "Tag: $tagName" -ForegroundColor Green
    exit 0
}

Write-Host "Hinweis: Es wird die in Windows integrierte SSH-Funktion genutzt." -ForegroundColor DarkGray
Write-Host "Wenn keine SSH-Keys eingerichtet sind, wirst du nach dem Passwort gefragt." -ForegroundColor DarkGray
$sshUserPrompt = Read-Host "SSH Benutzername fuer den Raspberry Pi (Standard: '$SshUser')"
$sshUser = if ([string]::IsNullOrWhiteSpace($sshUserPrompt)) { $SshUser } else { $sshUserPrompt }

$keepUserdata = if ($NoKeepUserdata) { 'false' } else { 'true' }

foreach ($server in $servers) {
    $baseUrl = "$($server.protocol)://$($server.host)$($server.update_subpath)"
    $zipPath = $buildArtifacts[$server.app_subpath]

    Write-Host "-------------------------------------------------" -ForegroundColor DarkGray
    Write-Host "Deploye auf: $baseUrl" -ForegroundColor Cyan
    Write-Host "  Version:       $Version"
    Write-Host "  Keep Userdata: $keepUserdata"
    Write-Host "  ZIP:           $(Split-Path $zipPath -Leaf)"
    if ($SshKey) {
        Write-Host "  SSH Key:       $SshKey"
    }
    Write-Host ''

    $hostParts = $server.host -split ':'
    $targetIp = $hostParts[0]
    $targetPort = if ($hostParts.Count -gt 1) { $hostParts[1] } else { "8000" }
    $localUrl = "http://127.0.0.1:${targetPort}$($server.update_subpath)"
    $fileName = Split-Path $zipPath -Leaf
    $remoteTmpFile = "/tmp/$fileName"

    Write-Host "  Kopiere ZIP via SCP nach $targetIp ..." -ForegroundColor DarkCyan
    $scpArgs = @()
    if ($SshKey) {
        $scpArgs += @("-i", $SshKey)
    }
    $scpArgs += @("$zipPath", "$sshUser@${targetIp}:$remoteTmpFile")
    & scp @scpArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  FEHLER bei SCP-Uebertragung nach $targetIp." -ForegroundColor Red
        continue
    }

    Write-Host "  Starte Update via SSH auf $targetIp ..." -ForegroundColor DarkCyan
    $curlCmd = "curl -s -X POST '$localUrl/api/update/upload' -F 'version=$Version' -F 'keep_userdata=$keepUserdata' -F `"file=@$remoteTmpFile`""
    $sshArgs = @()
    if ($SshKey) {
        $sshArgs += @("-i", $SshKey)
    }
    $sshArgs += @("$sshUser@${targetIp}", $curlCmd)
    
    $sshOutputJson = & ssh @sshArgs
    if ($LASTEXITCODE -eq 0 -and $sshOutputJson) {
        try {
            $sshOutput = $sshOutputJson | ConvertFrom-Json
            if ($sshOutput.status -eq 'success') {
                Write-Host "  Update erfolgreich!" -ForegroundColor Green
                Write-Host "    Version: $($sshOutput.version)"
                Write-Host "    Archiv:  $($sshOutput.archive)"
            } else {
                Write-Host "  FEHLER beim Update: $($sshOutput.status)" -ForegroundColor Red
            }
        } catch {
            Write-Host "  FEHLER: Unerwartete Antwort vom Server: $sshOutputJson" -ForegroundColor Red
        }
    } else {
        Write-Host "  FEHLER beim Update via SSH." -ForegroundColor Red
    }

    # Cleanup remote tmp file
    $sshCleanupArgs = @()
    if ($SshKey) {
        $sshCleanupArgs += @("-i", $SshKey)
    }
    $sshCleanupArgs += @("$sshUser@${targetIp}", "rm -f $remoteTmpFile")
    & ssh @sshCleanupArgs
    Write-Host ''
}

# -- 6. Cleanup ZIPs --------------------------------------------------
foreach ($zip in $buildArtifacts.Values) {
    if (Test-Path $zip) { Remove-Item $zip -Force }
}

Write-Host "=======================================================" -ForegroundColor Green
Write-Host "  Deploy abgeschlossen - Version $Version" -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Green
