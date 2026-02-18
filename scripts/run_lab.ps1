param(
  [switch]$Help,

  # Miner counts
  [int]$CpuMiners = 0,
  [int]$GpuMiners = 10,

  # Mining params
  [int]$DifficultyBits = 22,
  [int]$GpuBatch = 20000000,
  [int]$CpuTemplateRefreshMs = 0,
  [int]$TemplateRefresh = 1,

  # Network params
  [string]$CoordinatorHost = "127.0.0.1",
  [int]$CoordinatorPort = 8000,
  [int]$DashboardPort = 8050
)

if ($Help) {
  Write-Host @"
Usage: .\run_lab.ps1 [options]

Options:
  -Help                    Show this help message
  -CpuMiners <int>         Number of CPU miners to start (default: 2)
  -GpuMiners <int>         Number of GPU miners to start (default: 1)
  -DifficultyBits <int>    Mining difficulty in bits (default: 18)
  -GpuBatch <int>          GPU batch size (default: 2000000)
  -TemplateRefresh <int>   Refresh template every N attempts (default: 1)
  -CoordinatorHost <str>   Coordinator host (default: 127.0.0.1)
  -CoordinatorPort <int>   Coordinator port (default: 8000)
  -DashboardPort <int>     Dashboard port (default: 8050)
"@
  exit 0
}

$ErrorActionPreference = "Stop"

# Move to repo root (script folder -> repo root)
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

# ---------------------------
# Dependency check/install
# ---------------------------
try {
  $needsInstall = python -m pip install -r requirements.txt --dry-run 2>&1 | Select-String "Would install"
  if ($needsInstall) {
      Write-Host "Installing dependencies..."
      python -m pip install -r requirements.txt --quiet
      Write-Host "Dependencies installed."
  } else {
      Write-Host "Dependencies already satisfied."
  }
} catch {
  Write-Host "WARNING: pip dry-run check failed; attempting install anyway..."
  python -m pip install -r requirements.txt --quiet
}

$CoordinatorUrl = "http://$CoordinatorHost`:$CoordinatorPort"

Write-Host "Repo root: $RepoRoot"
Write-Host "Coordinator: $CoordinatorUrl"
Write-Host "CPU Miners: $CpuMiners"
Write-Host "GPU Miners: $GpuMiners"
Write-Host "DifficultyBits: $DifficultyBits"
Write-Host "GPU Batch: $GpuBatch"
Write-Host "Dashboard: http://$CoordinatorHost`:$DashboardPort"
Write-Host ""

# Track spawned processes
$script:childProcesses = @()

function Start-ChildPwsh($cmd) {
  $proc = Start-Process powershell -ArgumentList "-NoExit", "-Command", $cmd -PassThru
  $script:childProcesses += $proc
  return $proc
}

# ---------------------------
# Coordinator
# ---------------------------
$coordCmd = @"
`$env:DIFFICULTY_BITS='$DifficultyBits';
python -m uvicorn coordinator.app:app --host $CoordinatorHost --port $CoordinatorPort
"@
Start-ChildPwsh $coordCmd | Out-Null
Start-Sleep -Seconds 1

# ---------------------------
# CPU Miners
# ---------------------------
for ($i = 1; $i -le $CpuMiners; $i++) {
  $minerId = "cpu-$i"
  $minerCmd = @"
python -m miner.miner --coordinator $CoordinatorUrl --miner-id $minerId --template-refresh-ms $CpuTemplateRefreshMs
"@

  Start-ChildPwsh $minerCmd | Out-Null
  Start-Sleep -Milliseconds 200
}

# ---------------------------
# GPU Miners
# ---------------------------
for ($i = 1; $i -le $GpuMiners; $i++) {
  $minerId = "gpu-$i"
  $gpuCmd = @"
python -m miner.gpu_miner --coordinator $CoordinatorUrl --miner-id $minerId --gpu-batch $GpuBatch --template-refresh $TemplateRefresh
"@
  Start-ChildPwsh $gpuCmd | Out-Null
  Start-Sleep -Milliseconds 200
}

# ---------------------------
# Dashboard
# ---------------------------
$dashCmd = @"
`$env:COORDINATOR_URL='$CoordinatorUrl';
`$env:DASHBOARD_PORT='$DashboardPort';
`$env:DASH_HOST='$CoordinatorHost';
python dashboard/app.py
"@
Start-ChildPwsh $dashCmd | Out-Null

Write-Host ""
Write-Host "Started. Open:"
Write-Host " - Coordinator docs: $CoordinatorUrl/docs"
Write-Host " - Dashboard: http://$CoordinatorHost`:$DashboardPort"
Write-Host ""
Write-Host "Press Ctrl+C or close this window to stop all processes..."
Write-Host ""

function Stop-AllChildProcesses {
    Write-Host "`nStopping all child processes..."
    foreach ($p in $script:childProcesses) {
        if ($p -and !$p.HasExited) {
            try {
                Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
                Get-CimInstance Win32_Process |
                  Where-Object { $_.ParentProcessId -eq $p.Id } |
                  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
            } catch { }
        }
    }
    Write-Host "All processes stopped."
}

try {
    while ($true) {
        Start-Sleep -Seconds 1
        $allDead = $true
        foreach ($p in $script:childProcesses) {
            if ($p -and !$p.HasExited) { $allDead = $false; break }
        }
        if ($allDead) { Write-Host "All child processes have exited."; break }
    }
} finally {
    Stop-AllChildProcesses
}
