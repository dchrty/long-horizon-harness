#Requires -Version 5.1
<#
.SYNOPSIS
    Remove the agent-factory CLI and (optionally) its Docker artifacts.

.DESCRIPTION
    Reverses install.ps1: uninstalls the uv tool, then sweeps any
    agent-factory-* containers and images Docker has accumulated. Does
    NOT touch per-project `upstream.git/` or `agent_logs/` directories -
    those belong to your project, not the install.

.PARAMETER KeepContainers
    Skip removing agent-factory-* Docker containers.

.PARAMETER KeepImages
    Skip removing agent-factory-* Docker images.

.EXAMPLE
    .\scripts\uninstall.ps1
    .\scripts\uninstall.ps1 -KeepImages   # leave built images cached
#>
[CmdletBinding()]
param(
    [switch]$KeepContainers,
    [switch]$KeepImages
)

# Continue on errors - we want best-effort cleanup, not abort on first failure.
$ErrorActionPreference = 'Continue'

function Info { param([string]$m) Write-Host "==> $m" -ForegroundColor Cyan }
function OK   { param([string]$m) Write-Host "    ok: $m" -ForegroundColor Green }
function Warn { param([string]$m) Write-Host "    warn: $m" -ForegroundColor Yellow }

function Test-Command {
    param([Parameter(Mandatory)][string]$Name)
    $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

# --- 1. uv tool uninstall ---------------------------------------------
Info "Uninstalling agent-factory via uv..."
if (Test-Command 'uv') {
    & uv tool uninstall agent-factory
    $code = $LASTEXITCODE
    if ($code -eq 0) {
        OK "uv tool uninstall succeeded"
    } else {
        Warn "uv tool uninstall exited $code (likely not installed - that's fine)"
    }
} else {
    Warn "uv not on PATH - skipping uv tool uninstall step"
}

# --- 2. Docker containers ---------------------------------------------
if (-not $KeepContainers) {
    Info "Removing agent-factory-* Docker containers..."
    if (Test-Command 'docker') {
        $output = & docker ps -a --filter 'name=agent-factory-' --format '{{.Names}}'
        if ($LASTEXITCODE -ne 0) {
            Warn "docker ps exited $LASTEXITCODE (daemon not running?) - skipping container cleanup"
        } else {
            $names = @($output | Where-Object { $_ })
            if ($names.Count -eq 0) {
                OK "no agent-factory containers found"
            } else {
                foreach ($n in $names) {
                    & docker rm -f $n | Out-Null
                    if ($LASTEXITCODE -eq 0) { OK "removed container $n" }
                    else { Warn "failed to remove container $n (exit $LASTEXITCODE)" }
                }
            }
        }
    } else {
        Warn "docker not on PATH - skipping container cleanup"
    }
} else {
    Info "Skipping container cleanup (-KeepContainers)"
}

# --- 3. Docker images -------------------------------------------------
if (-not $KeepImages) {
    Info "Removing agent-factory-* Docker images..."
    if (Test-Command 'docker') {
        $output = & docker images --filter 'reference=agent-factory-*' --format '{{.Repository}}:{{.Tag}}'
        if ($LASTEXITCODE -ne 0) {
            Warn "docker images exited $LASTEXITCODE (daemon not running?) - skipping image cleanup"
        } else {
            $images = @($output | Where-Object { $_ })
            if ($images.Count -eq 0) {
                OK "no agent-factory images found"
            } else {
                foreach ($img in $images) {
                    & docker rmi -f $img | Out-Null
                    if ($LASTEXITCODE -eq 0) { OK "removed image $img" }
                    else { Warn "failed to remove image $img (exit $LASTEXITCODE)" }
                }
            }
        }
    } else {
        Warn "docker not on PATH - skipping image cleanup"
    }
} else {
    Info "Skipping image cleanup (-KeepImages)"
}

# --- 4. Verify --------------------------------------------------------
Info "Verifying removal..."
$existing = Get-Command agent-factory -ErrorAction SilentlyContinue
if ($existing) {
    Warn "agent-factory is STILL on PATH at: $($existing.Source)"
    Warn "If you just ran uv tool uninstall, open a new PowerShell window to confirm - Get-Command caches lookups within a session."
} else {
    OK "agent-factory removed from PATH"
}

Write-Host ""
Write-Host "Note: per-project state (upstream.git/, agent_logs/, verdicts.json) was NOT touched." -ForegroundColor DarkGray
Write-Host "Delete those manually inside any project you initialised if you want a clean slate." -ForegroundColor DarkGray
