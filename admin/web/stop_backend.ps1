$ErrorActionPreference = "SilentlyContinue"

$ports = @(8000, 8001)
$stopped = @()

foreach ($port in $ports) {
    $listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($conn in $listeners) {
        $process = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        if ($process -and $process.ProcessName -like "python*") {
            Stop-Process -Id $conn.OwningProcess -Force
            $stopped += "port $port, process $($conn.OwningProcess)"
        }
    }
}

if ($stopped.Count -eq 0) {
    Write-Output "No Python backend found on ports 8000/8001."
} else {
    Write-Output "Stopped:"
    $stopped | ForEach-Object { Write-Output $_ }
}
