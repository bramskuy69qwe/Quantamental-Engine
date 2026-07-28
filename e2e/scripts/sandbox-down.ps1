# Stop the sandbox engine (worktree + data stay for the next run).
#   powershell -File e2e/scripts/sandbox-down.ps1
$Sandbox = "E:\tmp\qe-sandbox"
$PidFile = Join-Path $Sandbox ".sandbox.pid"
if (Test-Path $PidFile) {
    $p = Get-Content $PidFile
    $proc = Get-Process -Id $p -ErrorAction SilentlyContinue
    if ($proc) {
        Stop-Process -Id $p -Force -Confirm:$false
        Write-Host "[sandbox] stopped (pid $p)"
    } else {
        Write-Host "[sandbox] not running"
    }
    Remove-Item $PidFile -Confirm:$false -ErrorAction SilentlyContinue
} else {
    Write-Host "[sandbox] no pid file"
}
