param(
  [switch]$Help,
  [int]$Miners = 3,
  [int]$DifficultyBits = 18,
  [string]$CoordinatorHost = "127.0.0.1",
  [int]$CoordinatorPort = 8000,
  [int]$DashboardPort = 8050
)

if ($Help) {
  Write-Host @"
Usage: .\run_lab.ps1 [options]

Options:
  -Help              Show this help message
  -Miners <int>      Number of miners to start (default: 3)
  -DifficultyBits <int>  Mining difficulty in bits (default: 18)
  -CoordinatorHost <string>  Coordinator host address (default: 127.0.0.1)
  -CoordinatorPort <int>     Coordinator port (default: 8000)
  -DashboardPort <int>       Dashboard port (default: 8050)

Examples:
  .\run_lab.ps1                           # Use all defaults
  .\run_lab.ps1 -Miners 5                 # Start 5 miners
  .\run_lab.ps1 -DifficultyBits 20        # Set difficulty to 20 bits
  .\run_lab.ps1 -Miners 5 -DifficultyBits 20 -DashboardPort 9000
"@
  exit 0
}

$ErrorActionPreference = "Stop"

# Move to repo root (script folder -> repo root)
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

$needsInstall = python -m pip install -r requirements.txt --dry-run 2>&1 | 
                Select-String "Would install"
if ($needsInstall) {
    Write-Host "Installing dependencies..."
    python -m pip install -r requirements.txt --quiet
    Write-Host "Dependencies installed."
} else {
    Write-Host "Dependencies already satisfied."
}

$CoordinatorUrl = "http://$CoordinatorHost`:$CoordinatorPort"

Write-Host "Repo root: $RepoRoot"
Write-Host "Coordinator: $CoordinatorUrl"
Write-Host "Miners: $Miners"
Write-Host "DifficultyBits: $DifficultyBits"
Write-Host "Dashboard: http://$CoordinatorHost`:$DashboardPort"
Write-Host ""

# Array to track all spawned processes
$script:childProcesses = @()

# ---------------------------
# Coordinator
# ---------------------------
# We set DIFFICULTY_BITS via env var (requires coordinator/app.py reading it).
$coordCmd = @"
`$env:DIFFICULTY_BITS='$DifficultyBits';
python -m uvicorn coordinator.app:app --host $CoordinatorHost --port $CoordinatorPort
"@

$proc = Start-Process powershell -ArgumentList "-NoExit", "-Command", $coordCmd -PassThru
$script:childProcesses += $proc
Start-Sleep -Seconds 1

# ---------------------------
# Miners
# ---------------------------
for ($i = 1; $i -le $Miners; $i++) {
  $minerId = "cpu-$i"
  $minerCmd = @"
python -m miner.miner --coordinator $CoordinatorUrl --miner-id $minerId
"@
  $proc = Start-Process powershell -ArgumentList "-NoExit", "-Command", $minerCmd -PassThru
  $script:childProcesses += $proc
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

$proc = Start-Process powershell -ArgumentList "-NoExit", "-Command", $dashCmd -PassThru
$script:childProcesses += $proc

Write-Host ""
Write-Host "Started. Open:"
Write-Host " - Coordinator docs: $CoordinatorUrl/docs"
Write-Host " - Dashboard: http://$CoordinatorHost`:$DashboardPort"
Write-Host ""
Write-Host "Press Ctrl+C or close this window to stop all processes..."
Write-Host ""

# Cleanup function to terminate all child processes
function Stop-AllChildProcesses {
    Write-Host "`nStopping all child processes..."
    foreach ($p in $script:childProcesses) {
        if ($p -and !$p.HasExited) {
            try {
                # Kill the process tree (including python subprocesses)
                Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
                # Also try to kill any child processes
                Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $p.Id } | ForEach-Object {
                    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
                }
            } catch {
                # Process may have already exited
            }
        }
    }
    Write-Host "All processes stopped."
}

# Register cleanup on script exit
try {
    # Keep the script running and wait for Ctrl+C
    while ($true) {
        Start-Sleep -Seconds 1
        
        # Check if any critical process has died
        $allDead = $true
        foreach ($p in $script:childProcesses) {
            if ($p -and !$p.HasExited) {
                $allDead = $false
                break
            }
        }
        if ($allDead) {
            Write-Host "All child processes have exited."
            break
        }
    }
} finally {
    Stop-AllChildProcesses
}
