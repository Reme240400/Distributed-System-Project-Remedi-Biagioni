param(
  [switch]$Help,

  # Miner counts
  [int]$CpuMiners = 0,
  [int]$GpuMiners = 3,

  # Mining params
  [int]$DifficultyBits = 22,
  [int]$GpuBatch = 20000,

  # Branch / sync params
  [int]$DifficultyAdjustmentInterval = 100,
  [int]$ReorgThreshold = 3,    #Quando il coordinator fa reorg
  [int]$SwitchLagBlocks = 3,   #Quanto scarto può avere il miner prima che chiede il template nuovo
  [int]$CpuHeadPollMs = 200,
  [int]$GpuHeadPollMs = 200,

  # Network delay
  [int]$NetworkDelayMinMs = 0,
  [int]$NetworkDelayMaxMs = 600,

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
  -CpuMiners <int>         Number of CPU miners
  -GpuMiners <int>         Number of GPU miners
  -DifficultyBits <int>    Mining difficulty in bits
  -GpuBatch <int>          GPU batch size
  -ReorgThreshold <int>    Coordinator reorg threshold in blocks
  -SwitchLagBlocks <int>   Miner switch threshold in blocks
  -CpuHeadPollMs <int>     CPU miner head polling interval in ms
  -GpuHeadPollMs <int>     GPU miner head polling interval in ms
  -NetworkDelayMinMs <int> Minimum simulated network delay in ms
  -NetworkDelayMaxMs <int> Maximum simulated network delay in ms
  -CoordinatorHost <str>   Coordinator host
  -CoordinatorPort <int>   Coordinator port
  -DashboardPort <int>     Dashboard port
"@
  exit 0
}

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

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
Write-Host "Reorg Threshold: $ReorgThreshold"
Write-Host "Switch Lag Blocks: $SwitchLagBlocks"
Write-Host "CPU Head Poll: $CpuHeadPollMs ms"
Write-Host "GPU Head Poll: $GpuHeadPollMs ms"
Write-Host "Network Delay Min: $NetworkDelayMinMs ms"
Write-Host "Network Delay Max: $NetworkDelayMaxMs ms"
Write-Host "Difficulty Adjustment Interval: $DifficultyAdjustmentInterval"
Write-Host "Dashboard: http://$CoordinatorHost`:$DashboardPort"
Write-Host ""

$script:childProcesses = @()

function Start-ChildPwsh($cmd) {
  $proc = Start-Process powershell -ArgumentList "-NoExit", "-Command", $cmd -PassThru
  $script:childProcesses += $proc
  return $proc
}

# Coordinator
$coordCmd = @"
`$env:DIFFICULTY_BITS='$DifficultyBits';
`$env:REORG_THRESHOLD='$ReorgThreshold';
`$env:DIFFICULTY_ADJUSTMENT_INTERVAL='$DifficultyAdjustmentInterval';
python -m uvicorn coordinator.app:app --host $CoordinatorHost --port $CoordinatorPort
"@
Start-ChildPwsh $coordCmd | Out-Null
Start-Sleep -Seconds 1

# CPU miners
for ($i = 1; $i -le $CpuMiners; $i++) {
  $minerId = "cpu-$i"
  $minerCmd = @"
python -m miner.miner --coordinator $CoordinatorUrl --miner-id $minerId --head-poll-ms $CpuHeadPollMs --switch-lag-blocks $SwitchLagBlocks --network-delay-min-ms $NetworkDelayMinMs --network-delay-max-ms $NetworkDelayMaxMs
"@
  Start-ChildPwsh $minerCmd | Out-Null
  Start-Sleep -Milliseconds 200
}

# GPU miners
for ($i = 1; $i -le $GpuMiners; $i++) {
  $minerId = "gpu-$i"
  $gpuCmd = @"
python -m miner.gpu_miner --coordinator $CoordinatorUrl --miner-id $minerId --gpu-batch $GpuBatch --head-poll-ms $GpuHeadPollMs --switch-lag-blocks $SwitchLagBlocks --network-delay-min-ms $NetworkDelayMinMs --network-delay-max-ms $NetworkDelayMaxMs
"@
  Start-ChildPwsh $gpuCmd | Out-Null
  Start-Sleep -Milliseconds 200
}

# Dashboard
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