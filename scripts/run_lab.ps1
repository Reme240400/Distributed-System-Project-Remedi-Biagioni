param(
  [int]$Miners = 3,
  [int]$DifficultyBits = 18,
  [string]$CoordinatorHost = "127.0.0.1",
  [int]$CoordinatorPort = 8000,
  [int]$DashboardPort = 8050
)

$ErrorActionPreference = "Stop"

# Move to repo root (script folder -> repo root)
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

$CoordinatorUrl = "http://$CoordinatorHost`:$CoordinatorPort"

Write-Host "Repo root: $RepoRoot"
Write-Host "Coordinator: $CoordinatorUrl"
Write-Host "Miners: $Miners"
Write-Host "DifficultyBits: $DifficultyBits"
Write-Host "Dashboard: http://$CoordinatorHost`:$DashboardPort"
Write-Host ""

# ---------------------------
# Coordinator
# ---------------------------
# We set DIFFICULTY_BITS via env var (requires coordinator/app.py reading it).
$coordCmd = @"
`$env:DIFFICULTY_BITS='$DifficultyBits';
python -m uvicorn coordinator.app:app --host $CoordinatorHost --port $CoordinatorPort
"@

Start-Process powershell -ArgumentList "-NoExit", "-Command", $coordCmd | Out-Null
Start-Sleep -Seconds 1

# ---------------------------
# Miners
# ---------------------------
for ($i = 1; $i -le $Miners; $i++) {
  $minerId = "cpu-$i"
  $minerCmd = @"
python miner/miner.py --coordinator $CoordinatorUrl --miner-id $minerId
"@
  Start-Process powershell -ArgumentList "-NoExit", "-Command", $minerCmd | Out-Null
  Start-Sleep -Milliseconds 200
}

# ---------------------------
# Dashboard
# ---------------------------
# Pass coordinator URL via env var if you want to run dashboard against different host/port.
$dashCmd = @"
`$env:COORDINATOR_URL='$CoordinatorUrl';
python dashboard/app.py
"@

Start-Process powershell -ArgumentList "-NoExit", "-Command", $dashCmd | Out-Null

Write-Host ""
Write-Host "Started. Open:"
Write-Host " - Coordinator docs: $CoordinatorUrl/docs"
Write-Host " - Dashboard: http://$CoordinatorHost`:$DashboardPort"
