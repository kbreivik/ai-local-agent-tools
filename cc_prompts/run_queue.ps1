# DEATHSTAR Prompt Queue Runner — PowerShell version for Windows Terminal
# Usage:
#   cd D:\claude_code\ai-local-agent-tools
#   .\cc_prompts\run_queue.ps1              # run all pending
#   .\cc_prompts\run_queue.ps1 -DryRun      # preview only
#   .\cc_prompts\run_queue.ps1 -One         # run just the next one

param(
    [switch]$DryRun,
    [switch]$One
)

$ErrorActionPreference = "Stop"

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$IndexFile   = Join-Path $ScriptDir "INDEX.md"
$RunnerFile  = Join-Path $ScriptDir "QUEUE_RUNNER.md"

# ── Helpers ───────────────────────────────────────────────────────────────────

function Log  { param($msg) Write-Host "[queue] $msg" -ForegroundColor Cyan }
function Warn { param($msg) Write-Host "[queue] WARN: $msg" -ForegroundColor Yellow }
function Fail { param($msg) Write-Host "[queue] ERROR: $msg" -ForegroundColor Red; exit 1 }

function Get-PendingCount {
    (Select-String -Path $IndexFile -Pattern "\| PENDING" -SimpleMatch).Count
}

function Get-NextPendingFile {
    $line = (Select-String -Path $IndexFile -Pattern "\| PENDING" -SimpleMatch |
             Select-Object -First 1).Line
    if (-not $line) { return $null }
    # Extract filename: column between first and second | after the leading |
    $parts = $line -split '\|'
    # Find the part that matches CC_PROMPT*.md
    foreach ($p in $parts) {
        $p = $p.Trim()
        if ($p -match '^CC_PROMPT.*\.md$') { return $p }
    }
    return $null
}

function Get-NextPendingVersion {
    $line = (Select-String -Path $IndexFile -Pattern "\| PENDING" -SimpleMatch |
             Select-Object -First 1).Line
    if (-not $line) { return "?" }
    $parts = $line -split '\|'
    foreach ($p in $parts) {
        $p = $p.Trim()
        if ($p -match '^v\d') { return $p }
    }
    return "?"
}

# ── Preflight ─────────────────────────────────────────────────────────────────

Set-Location $ProjectRoot
Log "Project root: $ProjectRoot"
Log "Index: $IndexFile"

# Check claude CLI
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Fail "claude CLI not found. Install: npm install -g @anthropic-ai/claude-code"
}

# Check git
try { git rev-parse --git-dir 2>$null | Out-Null }
catch { Fail "Not in a git repository" }

Log "Git branch: $(git branch --show-current)"

# Only warn on modified tracked files (not untracked)
$modified = git diff --name-only
if ($modified) {
    Warn "Modified tracked files before queue run:"
    $modified | ForEach-Object { Write-Host "  $_" }
    $answer = Read-Host "[queue] Continue anyway? (y/N)"
    if ($answer -notmatch '^[Yy]$') { exit 1 }
}

# ── Dry run ───────────────────────────────────────────────────────────────────

if ($DryRun) {
    $count = Get-PendingCount
    Log "Queue status — $count prompt(s) PENDING:"
    Write-Host ""
    $lines = Select-String -Path $IndexFile -Pattern "\| PENDING|\| DONE" -SimpleMatch |
             ForEach-Object { $_.Line }
    foreach ($line in $lines) {
        $parts = ($line -split '\|') | ForEach-Object { $_.Trim() } | Where-Object { $_ }
        if ($parts.Count -ge 3) {
            Write-Host ("  {0,-12} {1,-65} {2}" -f $parts[1], $parts[2], $parts[3])
        }
    }
    Write-Host ""
    exit 0
}

# ── Main loop ─────────────────────────────────────────────────────────────────

$RunCount = 0
$MaxRuns  = 10

while ($true) {
    $count = Get-PendingCount
    if ($count -eq 0) {
        Log "Queue complete — all prompts done."
        break
    }
    if ($RunCount -ge $MaxRuns) {
        Log "Safety cap ($MaxRuns runs). Re-run to continue."
        break
    }

    $nextFile = Get-NextPendingFile
    $nextVer  = Get-NextPendingVersion
    $promptPath = Join-Path $ScriptDir $nextFile

    if (-not $nextFile) { Fail "Could not parse next PENDING file from INDEX.md" }
    if (-not (Test-Path $promptPath)) { Fail "Prompt file not found: $promptPath" }

    Write-Host ""
    Log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    Log "Running: $nextVer — $nextFile  ($count pending)"
    Log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    $beforeHash = git rev-parse HEAD

    # Build the task string
    $runnerContent = Get-Content $RunnerFile -Raw
    $promptContent = Get-Content $promptPath -Raw
    $task = @"
You are running in automated queue mode for the DEATHSTAR project.

$runnerContent

---

The prompt to implement right now is: $nextFile (version $nextVer)

Prompt content:

$promptContent

After implementing and pushing, update cc_prompts/INDEX.md: change the status
for $nextFile from 'PENDING' to 'DONE (SHA)' where SHA is the short git hash,
then commit and push that index change too.
"@

    # Write task to temp file (avoids shell quoting issues with long strings)
    $tempTask = Join-Path $env:TEMP "deathstar_queue_task.txt"
    $task | Out-File -FilePath $tempTask -Encoding utf8

    # Invoke Claude Code — reads task from stdin
    try {
        Get-Content $tempTask | claude --dangerously-skip-permissions
        $exitCode = $LASTEXITCODE
    }
    catch {
        $exitCode = 1
    }
    finally {
        Remove-Item $tempTask -ErrorAction SilentlyContinue
    }

    if ($exitCode -ne 0) {
        Fail "claude exited with code $exitCode for $nextFile — queue stopped."
    }

    $afterHash = git rev-parse HEAD
    if ($beforeHash -eq $afterHash) {
        Warn "Git hash unchanged after CC run — $nextFile may not have committed."
        Warn "Check: git log --oneline -5"
        Warn "Queue paused. Fix and re-run."
        exit 1
    }

    $short = git rev-parse --short HEAD
    Log "✓ $nextVer committed as $short"

    $RunCount++

    if ($One) {
        Log "--One flag set, stopping after first prompt."
        break
    }

    Log "Pausing 3s before next prompt..."
    Start-Sleep 3
}

Write-Host ""
Log "Session: $RunCount prompt(s) executed. Remaining: $(Get-PendingCount)"
git log --oneline -5
