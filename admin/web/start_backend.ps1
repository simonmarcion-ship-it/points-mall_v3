$ErrorActionPreference = "Stop"

$port = 8001
$webDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($listeners) {
    Write-Output "Backend is already running: http://127.0.0.1:$port"
    exit 0
}

Start-Process -FilePath python `
    -ArgumentList '-m','uvicorn','backend.main:app','--host','127.0.0.1','--port',"$port" `
    -WorkingDirectory $webDir `
    -WindowStyle Hidden

Start-Sleep -Seconds 3

try {
    $summary = Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/summary" -UseBasicParsing -TimeoutSec 10
    Write-Output "Backend started: http://127.0.0.1:$port"
    Write-Output $summary.Content
} catch {
    Write-Output "Backend start command ran, but health check failed: $($_.Exception.Message)"
}
