#Requires -Version 5.1
<#
.SYNOPSIS
    Install the agent-factory CLI globally via uv tool install.

.DESCRIPTION
    Verifies prerequisites (uv, docker, claude), then runs
    `uv tool install <repo>` so the `agent-factory` command is on PATH
    from any directory. Safe to re-run; pass -Reinstall to force.

    Two modes:
      Default (frozen):  uv builds a wheel from the source tree and
                         installs it. To pick up edits, re-run with
                         -Reinstall.
      -Editable:         the installed shim points at the source tree
                         directly. Edits to .py files take effect
                         immediately with no reinstall. Recommended
                         for active harness development.

.PARAMETER Reinstall
    Pass --reinstall to uv tool install. Use after pulling new commits,
    or when switching between frozen and editable modes. Implied when
    -Editable is passed.

.PARAMETER InstallUv
    If uv is missing, run the official Astral installer instead of
    failing. Off by default so each step is visible.

.PARAMETER Editable
    Install in editable/development mode (uv tool install --editable).
    Source edits take effect without reinstalling. Only re-run install
    if pyproject.toml or entry points change.

.EXAMPLE
    .\scripts\install.ps1                  # frozen install
    .\scripts\install.ps1 -Editable        # dev install, hot-reload edits
    .\scripts\install.ps1 -Reinstall       # after git pull, frozen
    .\scripts\install.ps1 -InstallUv       # auto-install uv if missing
#>
[CmdletBinding()]
param(
    [switch]$Reinstall,
    [switch]$InstallUv,
    [switch]$Editable
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot

function Test-Command {
    param([Parameter(Mandatory)][string]$Name)
    $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Info { param([string]$m) Write-Host "==> $m" -ForegroundColor Cyan }
function OK   { param([string]$m) Write-Host "    ok: $m" -ForegroundColor Green }
function Warn { param([string]$m) Write-Host "    warn: $m" -ForegroundColor Yellow }
function Fail {
    param([string]$m)
    Write-Host ""
    Write-Host "ERROR: $m" -ForegroundColor Red
    exit 1
}

# Tracks runtime-only deps that are missing. Reported at the end so the
# user has one consolidated reminder of what to install before first run.
$script:RuntimeWarnings = @()

Info "agent-factory install (repo: $RepoRoot)"
Info "Checking prerequisites..."

# --- uv ---------------------------------------------------------------
if (-not (Test-Command 'uv')) {
    if ($InstallUv) {
        Info "uv not found; running official Astral installer..."
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
        $uvBin = Join-Path $env:USERPROFILE '.local\bin'
        if (-not (Test-Path (Join-Path $uvBin 'uv.exe'))) {
            Fail "uv installer ran but uv.exe not at $uvBin\uv.exe. Open a new PowerShell window and re-run this script."
        }
        # Make uv visible in *this* session. The installer already added
        # this dir to the User PATH, so new shells will pick it up too.
        if (($env:Path -split ';') -notcontains $uvBin) {
            $env:Path = "$uvBin;$env:Path"
        }
        OK "uv installed; added to current session PATH"
    } else {
        Fail @"
uv is not on PATH.

Install it with:
  irm https://astral.sh/uv/install.ps1 | iex

...then open a new PowerShell window and re-run this script,
or re-run now with -InstallUv to auto-install.
"@
    }
}
$uvVersion = (& uv --version) -join ' '
OK "uv -> $uvVersion"

# --- docker (runtime dep; daemon check happens at agent-factory run) --
# Not required at install time. The CLI installs fine without docker;
# `agent-factory run` will check for the daemon and fail with a clear
# error then.
if (Test-Command 'docker') {
    $dockerVersion = (& docker --version) -join ' '
    OK "docker -> $dockerVersion"
} else {
    Warn "docker CLI not on PATH (runtime dep - install Docker Desktop before first run)"
    $script:RuntimeWarnings += 'Docker Desktop: https://www.docker.com/products/docker-desktop/'
}

# --- claude CLI (runtime dep) -----------------------------------------
if (Test-Command 'claude') {
    $claudeVersion = (& claude --version) -join ' '
    OK "claude -> $claudeVersion"
} else {
    Warn "claude CLI not on PATH (runtime dep - the harness inherits your host login)"
    $script:RuntimeWarnings += 'Claude Code CLI: https://docs.claude.com/en/docs/claude-code/setup'
}

# --- install ----------------------------------------------------------
$mode = if ($Editable) { 'editable (dev)' } else { 'frozen' }
Info "Installing agent-factory via uv ($mode mode)..."
$installArgs = @('tool', 'install', $RepoRoot)
# -Editable always implies a reinstall so users can switch modes without
# hitting "already installed" errors from uv.
if ($Reinstall -or $Editable) { $installArgs += '--reinstall' }
if ($Editable) { $installArgs += '--editable' }
& uv @installArgs
if ($LASTEXITCODE -ne 0) {
    Fail "uv tool install exited $LASTEXITCODE. If it complained about an existing install, re-run with -Reinstall."
}

# --- verify -----------------------------------------------------------
Info "Verifying install..."
# Get-Command caches; force a fresh PATH probe by clearing the cache first.
Get-Command agent-factory -ErrorAction SilentlyContinue | Out-Null
if (-not (Test-Command 'agent-factory')) {
    $binDir = (& uv tool dir --bin 2>$null) -join ''
    Fail @"
agent-factory installed but not on PATH in this session.

uv tool bin directory:
  $binDir

Open a NEW PowerShell window - uv added that directory to your User PATH
during the first install, but the current session is stuck with its
original PATH. After opening a new window, run `agent-factory --help`
to confirm.
"@
}

& agent-factory --help | Out-Null
if ($LASTEXITCODE -ne 0) {
    Fail "agent-factory is on PATH but '--help' exited $LASTEXITCODE."
}
$afLocation = (Get-Command agent-factory).Source
OK "agent-factory -> $afLocation"

Write-Host ""
if ($script:RuntimeWarnings.Count -gt 0) {
    Write-Host "Install before first run:" -ForegroundColor Yellow
    foreach ($w in $script:RuntimeWarnings) {
        Write-Host "  - $w" -ForegroundColor Yellow
    }
    Write-Host ""
}
Info "Done. Next steps:"
Write-Host "  cd <your-project>           # must contain a GOAL.md"
Write-Host "  agent-factory init"
Write-Host "  agent-factory run 1 10      # 1 agent, 10 min (smoke test)"
Write-Host ""
if ($Editable) {
    Write-Host "Editable install: edits to agent_factory/*.py take effect on next" -ForegroundColor DarkGray
    Write-Host "agent-factory invocation - no reinstall needed. Re-run install only" -ForegroundColor DarkGray
    Write-Host "if pyproject.toml or entry points change." -ForegroundColor DarkGray
} else {
    Write-Host "Frozen install: re-run with -Reinstall after editing harness code." -ForegroundColor DarkGray
    Write-Host "For faster iteration, use -Editable to skip the reinstall step." -ForegroundColor DarkGray
}
Write-Host ""
Write-Host "To uninstall: .\scripts\uninstall.ps1"
