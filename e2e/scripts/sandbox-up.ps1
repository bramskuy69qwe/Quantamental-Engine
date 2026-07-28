# Stand up the SANDBOX engine for Phase-4 mutation/degraded testing.
#
#   powershell -File e2e/scripts/sandbox-up.ps1 [-Wipe] [-SkipProvision]
#
# Safety architecture (do not weaken):
#  - The worktree lives OUTSIDE the repo (E:\tmp\qe-sandbox): config.py's bare
#    load_dotenv() walks UP the directory tree - an in-repo worktree would
#    inherit the operator's REAL Binance keys and open a second user-data
#    socket on the live account.
#  - A shadow .env with a throwaway ENV_MASTER_KEY and EMPTY provider keys is
#    written BEFORE any python import of config. provision_test_env.py's own
#    credential blanking is process-local and not sufficient alone.
#  - provision_test_env.py refuses primary checkouts and live-shaped data on
#    its own; this script never touches the live tree's data/.
#
# The engine launches on 127.0.0.1:8010 (never --reload: reload workers
# double-run the schedulers). Console out/err -> $Sandbox\sandbox-console.log
# (catches stderr tracebacks the JSON log never sees). PID -> .sandbox.pid.

param(
    [switch]$Wipe,
    [switch]$SkipProvision
)
$ErrorActionPreference = 'Stop'

$Repo    = "E:\Quantamental Models\Quantamental Engine v2.0\Quantamental Engine v2.0 Code Base"
$Sandbox = "E:\tmp\qe-sandbox"
$Py      = Join-Path $Repo ".venv\Scripts\python.exe"
$Port    = 8010

# 1. Worktree (detached - the sandbox never commits)
if (-not (Test-Path (Join-Path $Sandbox ".git"))) {
    New-Item -ItemType Directory -Force (Split-Path $Sandbox) | Out-Null
    Push-Location $Repo
    git worktree add --detach $Sandbox HEAD
    Pop-Location
    Write-Host "[sandbox] worktree created at $Sandbox"
} else {
    Write-Host "[sandbox] worktree exists"
}

# 2. Shadow .env (throwaway master key, EMPTY provider keys)
$EnvPath = Join-Path $Sandbox ".env"
if (-not (Test-Path $EnvPath)) {
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $bytes = New-Object byte[] 32; $rng.GetBytes($bytes)
    $key = ($bytes | ForEach-Object { $_.ToString('x2') }) -join ''
    @(
        "# SANDBOX shadow env - shadows the parent-walk of load_dotenv().",
        "# Throwaway master key; provider keys deliberately EMPTY.",
        "ENV_MASTER_KEY=$key",
        "BINANCE_API_KEY=",
        "BINANCE_API_SECRET=",
        "FINNHUB_API_KEY=",
        "FRED_API_KEY=",
        "COINGECKO_API_KEY="
    ) | Out-File -Encoding ascii $EnvPath
    Write-Host "[sandbox] shadow .env written"
}

# 3. Provision (split-DB layout, empty creds, scrub-verified)
if (-not $SkipProvision) {
    Push-Location $Sandbox
    $provArgs = @("scripts\provision_test_env.py")
    if ($Wipe) { $provArgs += "--wipe" }
    & $Py @provArgs
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "[sandbox] provision failed ($LASTEXITCODE)" }
    Pop-Location
}

# 4. Launch uvicorn on :$Port (never --reload)
$PidFile = Join-Path $Sandbox ".sandbox.pid"
if (Test-Path $PidFile) {
    $old = Get-Content $PidFile
    if (Get-Process -Id $old -ErrorAction SilentlyContinue) {
        Write-Host "[sandbox] already running (pid $old)"; exit 0
    }
}
$LogFile = Join-Path $Sandbox "sandbox-console.log"
$proc = Start-Process -FilePath $Py `
    -ArgumentList "-m","uvicorn","main:app","--host","127.0.0.1","--port","$Port" `
    -WorkingDirectory $Sandbox -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $LogFile -RedirectStandardError ($LogFile + '.err')
$proc.Id | Out-File -Encoding ascii $PidFile
Write-Host "[sandbox] engine starting (pid $($proc.Id)) on :$Port"

# 5. Verify boot (red WS + empty exchange state is the EXPECTED shape)
$ok = $false
for ($i = 0; $i -lt 45; $i++) {
    Start-Sleep -Seconds 2
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/v3" -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch {}
    if ($proc.HasExited) { break }
}
if (-not $ok) {
    Write-Host "[sandbox] BOOT FAILED - console tail:"
    Get-Content ($LogFile + '.err') -Tail 25 -ErrorAction SilentlyContinue
    Get-Content $LogFile -Tail 15 -ErrorAction SilentlyContinue
    exit 1
}
Write-Host "[sandbox] UP - http://127.0.0.1:$Port/v3"
