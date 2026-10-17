<#
Start the backend stack on Windows, then replay a scenario (Workstream A).

    .\run_scenario.ps1 1             # build, start, replay scenario 1
    .\run_scenario.ps1 5 -Burst      # concurrency burst
    .\run_scenario.ps1 1 -Reset      # wipe Talos and the graphs first
    .\run_scenario.ps1 -Demo         # whole demo, step by step
    .\run_scenario.ps1               # just start the stack
    .\run_scenario.ps1 -NoBuild 2a   # skip the image builds
    .\run_scenario.ps1 -Down         # stop everything

Builds by hand because Compose v5 `up --build` fails on Windows (CLAUDE.md). Replay logic
lives in scripts/replay_scenario.py; this file only starts things and passes the arguments on.
#>
param(
    [string]$Scenario,
    [switch]$Burst,
    [switch]$Reset,
    [switch]$Demo,
    [switch]$NoBuild,
    [switch]$Down,
    [int]$Agents = 2
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Invoke-Checked {
    & $args[0] @($args | Select-Object -Skip 1)
    if ($LASTEXITCODE) { throw "failed ($LASTEXITCODE): $args" }
}

if ($Down) {
    Invoke-Checked docker compose --profile app down
    return
}

# Postgres refuses to start with an empty password.
if (-not (Select-String -Path .env -Pattern '^TALOS_DB_PASSWORD=.+' -Quiet)) {
    throw "set TALOS_DB_PASSWORD in .env first"
}

if (-not $NoBuild) {
    Invoke-Checked docker build -f deploy/agents.Dockerfile -t argus-soc-python:local .
    Invoke-Checked docker build -f deploy/talos/Dockerfile -t argus-soc-talos .
}

# ponytail: backend only; add api ui nginx here once Workstream C's API and UI exist.
# `up -d` returns once seed has finished and Talos is healthy (depends_on conditions).
Invoke-Checked docker compose --profile app up -d --no-build --scale agents=$Agents `
    falkordb seed talos-postgres talos ingestor agents

$replay = @()
if ($Scenario) { $replay += $Scenario }
if ($Burst) { $replay += "--burst" }
if ($Reset) { $replay += "--reset" }
if ($Demo) { $replay += "--demo" }
if ($replay.Count -eq 0) {
    Write-Host "stack up. Graph: http://127.0.0.1:3000  Logs: docker compose logs -f agents ingestor"
    return
}

$python = if (Test-Path .venv\Scripts\python.exe) { ".venv\Scripts\python.exe" } else { "python" }
Invoke-Checked $python scripts/replay_scenario.py @replay
Write-Host "done. Graph: http://127.0.0.1:3000  Logs: docker compose logs -f agents ingestor"
