# AgentHub one-command dev launcher (PowerShell 5+)
# Starts PostgreSQL (if needed), backend (8001), frontend (5173), then opens the browser.
# The script stays in the foreground and supervises both services.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\dev.ps1
#   powershell -ExecutionPolicy Bypass -File .\dev.ps1 -NoBrowser

param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $root 'agenthub'
$frontendDir = Join-Path $root 'frontend'
$python = Join-Path $backendDir '.venv\Scripts\python.exe'

$backendLog = Join-Path $env:TEMP 'agenthub-backend.log'
$backendErr = Join-Path $env:TEMP 'agenthub-backend.err.log'
$frontendLog = Join-Path $env:TEMP 'agenthub-frontend.log'
$frontendErr = Join-Path $env:TEMP 'agenthub-frontend.err.log'
$demoMcpLog = Join-Path $env:TEMP 'agenthub-demo-mcp.log'
$demoMcpErr = Join-Path $env:TEMP 'agenthub-demo-mcp.err.log'
$weatherMcpLog = Join-Path $env:TEMP 'agenthub-weather-mcp.log'
$weatherMcpErr = Join-Path $env:TEMP 'agenthub-weather-mcp.err.log'
$docMcpLog = Join-Path $env:TEMP 'agenthub-document-mcp.log'
$docMcpErr = Join-Path $env:TEMP 'agenthub-document-mcp.err.log'
$demoLlmLog = Join-Path $env:TEMP 'agenthub-demo-llm.log'
$demoLlmErr = Join-Path $env:TEMP 'agenthub-demo-llm.err.log'

function Test-Port([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(800)) { return $false }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Wait-Backend([int]$TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $health = Invoke-RestMethod 'http://127.0.0.1:8001/api/health' -TimeoutSec 2
            if ($health.status -eq 'ok') { return $true }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function New-SecretKey {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    return [Convert]::ToBase64String($bytes)
}

function Set-DotEnvValue([string]$Key, [string]$Value) {
    $lines = @()
    if (Test-Path $envFile) { $lines = @(Get-Content $envFile) }
    $found = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match ("^" + [regex]::Escape($Key) + "=")) {
            $lines[$i] = "$Key=$Value"
            $found = $true
        }
    }
    if (-not $found) { $lines += "$Key=$Value" }
    Set-Content -Path $envFile -Value $lines -Encoding ASCII
}

function Test-DbCredentials([int]$Port) {
    $probe = @"
import asyncio, asyncpg
async def m():
    conn = await asyncio.wait_for(asyncpg.connect(host='127.0.0.1', port=$Port, user='agenthub', password='agenthub', database='agenthub'), timeout=3)
    await conn.close()
asyncio.run(m())
"@
    # PS5 下原生命令写 stderr 会触发 NativeCommandError；探测失败属预期，必须降级为 Continue
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $python -c $probe 2>&1 | Out-Null
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    return ($exitCode -eq 0)
}

function Start-ComposePostgres([int]$Port) {
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if ($docker -eq $null) {
        throw "PostgreSQL is not reachable on port $Port and Docker is not installed."
    }
    Write-Host "Starting project PostgreSQL on 127.0.0.1:$Port ..."
    Push-Location $root
    try {
        $env:AGENTHUB_DB_PORT = "$Port"
        & $docker.Source compose up -d postgres
    } finally {
        Pop-Location
    }
    for ($i = 0; $i -lt 60; $i++) {
        if ((Test-Port $Port) -and (Test-DbCredentials $Port)) { return }
        Start-Sleep -Seconds 1
    }
    throw "PostgreSQL on 127.0.0.1:$Port did not become ready (agenthub/agenthub)."
}

function Show-LogTail([string]$Path, [int]$Lines = 40) {
    if (Test-Path $Path) {
        Write-Host "---- $Path ----"
        Get-Content $Path -Tail $Lines
    }
}

function Stop-ProcessTree([System.Diagnostics.Process]$Proc) {
    if ($Proc -ne $null -and -not $Proc.HasExited) {
        & taskkill /PID $Proc.Id /T /F | Out-Null
    }
}

Write-Host '== AgentHub dev launcher =='

# 1) Python venv
if (-not (Test-Path $python)) {
    throw "Python venv not found: $python. Create it with: cd agenthub; python -m venv .venv; .venv\Scripts\pip install -e ."
}

# 1.1) Keep venv in sync with pyproject (new deps such as cryptography must exist)
$previous = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    & $python -c "import cryptography, fastapi, langgraph, sqlalchemy, asyncpg, docx, reportlab, multipart" 2>&1 | Out-Null
    $depsCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $previous
}
if ($depsCode -ne 0) {
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv -eq $null) {
        throw 'Backend dependencies are missing. Run: cd agenthub; uv sync --all-groups'
    }
    Write-Host 'Backend dependencies are out of date; running uv sync ...'
    Push-Location $backendDir
    try {
        & $uv.Source sync --all-groups
    } finally {
        Pop-Location
    }
}

# 2) Local .env (SECRET_KEY is required for Model API encryption)
$envFile = Join-Path $backendDir '.env'
if (-not (Test-Path $envFile)) {
    Set-Content -Path $envFile -Value ("SECRET_KEY=" + (New-SecretKey)) -Encoding ASCII
    Write-Host 'Created agenthub/.env with a random SECRET_KEY'
} else {
    $envText = Get-Content $envFile -Raw
    if ($envText -notmatch '(?m)^SECRET_KEY=') {
        Add-Content -Path $envFile -Value ("SECRET_KEY=" + (New-SecretKey)) -Encoding ASCII
        Write-Host 'Added SECRET_KEY to agenthub/.env'
    }
}
$envText = Get-Content $envFile -Raw
if ($envText -notmatch '(?m)^ALLOW_PRIVATE_MCP=') {
    Add-Content -Path $envFile -Value 'ALLOW_PRIVATE_MCP=true' -Encoding ASCII
    Write-Host 'Enabled ALLOW_PRIVATE_MCP for local demo servers'
}

# 3) PostgreSQL
# 优先复用 5432 上凭据可用的实例；被本机其他 PostgreSQL 占用时，项目容器回退到 5433。
$dbPort = $null
if (Test-DbCredentials 5432) {
    $dbPort = 5432
} elseif (Test-DbCredentials 5433) {
    $dbPort = 5433
} elseif (-not (Test-Port 5432)) {
    Start-ComposePostgres 5432
    $dbPort = 5432
} elseif (-not (Test-Port 5433)) {
    Write-Host 'Port 5432 is occupied by another PostgreSQL instance; using 5433 for the project database.'
    Start-ComposePostgres 5433
    $dbPort = 5433
} else {
    throw 'Ports 5432/5433 are occupied but neither accepts agenthub/agenthub. Free one port or set DATABASE_URL in agenthub/.env.'
}
Set-DotEnvValue 'DATABASE_URL' "postgresql+asyncpg://agenthub:agenthub@127.0.0.1:$dbPort/agenthub"
Write-Host "PostgreSQL OK (127.0.0.1:$dbPort)."

# 4) Backend
$backendProc = $null
$backendHealthy = $false
try {
    $health = Invoke-RestMethod 'http://127.0.0.1:8001/api/health' -TimeoutSec 2
    $backendHealthy = ($health.status -eq 'ok')
} catch { }

if (-not $backendHealthy) {
    if (Test-Port 8001) {
        throw 'Port 8001 is occupied by another process. Stop it first.'
    }
    Write-Host 'Starting backend on http://127.0.0.1:8001 ...'
    Remove-Item $backendLog, $backendErr -ErrorAction SilentlyContinue
    $backendProc = Start-Process -FilePath $python `
        -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--reload', '--host', '127.0.0.1', '--port', '8001') `
        -WorkingDirectory $backendDir -NoNewWindow `
        -RedirectStandardOutput $backendLog -RedirectStandardError $backendErr -PassThru

    if (-not (Wait-Backend 90)) {
        Show-LogTail $backendErr
        Show-LogTail $backendLog
        Stop-ProcessTree $backendProc
        throw 'Backend did not become healthy within 90s.'
    }
    Write-Host 'Backend OK.'
} else {
    Write-Host 'Backend already running on 8001.'
}

# 5) Frontend
# 直接调用 node + vite.js，避免 npm.cmd 在非交互环境下找不到同目录的 node.exe。
$node = $null
$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
if ($nodeCommand -ne $null) {
    $node = $nodeCommand.Source
}
if ($node -eq $null) {
    $nodeCandidates = @(
        'C:\Program Files\Huawei\DevEco Studio\tools\node\node.exe',
        'C:\Program Files\nodejs\node.exe'
    )
    foreach ($candidate in $nodeCandidates) {
        if (Test-Path $candidate) { $node = $candidate; break }
    }
}
if ($node -eq $null) {
    throw 'node.exe not found. Install Node.js or run "npm run dev" in frontend manually.'
}

$viteBin = Join-Path $frontendDir 'node_modules\vite\bin\vite.js'
if (-not (Test-Path $viteBin)) {
    throw 'frontend/node_modules is missing. Run: cd frontend; npm install'
}
foreach ($module in @('vue', 'vue-router', 'mammoth', 'pdfjs-dist')) {
    if (-not (Test-Path (Join-Path $frontendDir "node_modules\$module"))) {
        throw "frontend/node_modules is out of date (missing $module). Run: cd frontend; npm install"
    }
}

$frontendProc = $null
if (-not (Test-Port 5173)) {
    Write-Host 'Starting frontend on http://localhost:5173 ...'
    Remove-Item $frontendLog, $frontendErr -ErrorAction SilentlyContinue
    $frontendProc = Start-Process -FilePath $node `
        -ArgumentList @($viteBin, '--host', '0.0.0.0', '--port', '5173', '--strictPort') `
        -WorkingDirectory $frontendDir -NoNewWindow `
        -RedirectStandardOutput $frontendLog -RedirectStandardError $frontendErr -PassThru

    $started = $false
    for ($i = 0; $i -lt 120; $i++) {
        if (Test-Port 5173) { $started = $true; break }
        if ($frontendProc.HasExited) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $started) {
        Show-LogTail $frontendErr
        Show-LogTail $frontendLog
        Stop-ProcessTree $frontendProc
        Stop-ProcessTree $backendProc
        throw 'Frontend did not start within 60s.'
    }
    Write-Host 'Frontend OK.'
} else {
    Write-Host 'Frontend already running on 5173.'
}

# 6) Local demo servers: MCP tools + OpenAI-compatible LLM
$demoMcpProc = $null
if (-not (Test-Port 8100)) {
    Write-Host 'Starting demo MCP server on http://127.0.0.1:8100/mcp ...'
    Remove-Item $demoMcpLog, $demoMcpErr -ErrorAction SilentlyContinue
    $demoMcpProc = Start-Process -FilePath $python `
        -ArgumentList @('-m', 'demo_mcp_server', '--host', '127.0.0.1', '--port', '8100') `
        -WorkingDirectory $backendDir -NoNewWindow `
        -RedirectStandardOutput $demoMcpLog -RedirectStandardError $demoMcpErr -PassThru
    $started = $false
    for ($i = 0; $i -lt 60; $i++) {
        if (Test-Port 8100) { $started = $true; break }
        if ($demoMcpProc.HasExited) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $started) {
        Show-LogTail $demoMcpErr
        Show-LogTail $demoMcpLog
        Stop-ProcessTree $demoMcpProc
        Stop-ProcessTree $frontendProc
        Stop-ProcessTree $backendProc
        throw 'Demo MCP server did not start within 30s.'
    }
    Write-Host 'Demo MCP OK.'
} else {
    Write-Host 'Demo MCP already running on 8100.'
}

$weatherMcpProc = $null
if (-not (Test-Port 8102)) {
    Write-Host 'Starting weather MCP server on http://127.0.0.1:8102/mcp ...'
    Remove-Item $weatherMcpLog, $weatherMcpErr -ErrorAction SilentlyContinue
    $weatherMcpProc = Start-Process -FilePath $python `
        -ArgumentList @('-m', 'weather_mcp_server', '--host', '127.0.0.1', '--port', '8102') `
        -WorkingDirectory $backendDir -NoNewWindow `
        -RedirectStandardOutput $weatherMcpLog -RedirectStandardError $weatherMcpErr -PassThru
    $started = $false
    for ($i = 0; $i -lt 60; $i++) {
        if (Test-Port 8102) { $started = $true; break }
        if ($weatherMcpProc.HasExited) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $started) {
        Show-LogTail $weatherMcpErr
        Show-LogTail $weatherMcpLog
        Stop-ProcessTree $weatherMcpProc
        Stop-ProcessTree $frontendProc
        Stop-ProcessTree $backendProc
        throw 'Weather MCP server did not start within 30s.'
    }
    Write-Host 'Weather MCP OK.'
} else {
    Write-Host 'Weather MCP already running on 8102.'
}

$docMcpProc = $null
if (-not (Test-Port 8103)) {
    Write-Host 'Starting document MCP server on http://127.0.0.1:8103/mcp ...'
    Remove-Item $docMcpLog, $docMcpErr -ErrorAction SilentlyContinue
    $docMcpProc = Start-Process -FilePath $python `
        -ArgumentList @('-m', 'document_mcp_server', '--host', '127.0.0.1', '--port', '8103') `
        -WorkingDirectory $backendDir -NoNewWindow `
        -RedirectStandardOutput $docMcpLog -RedirectStandardError $docMcpErr -PassThru
    $started = $false
    for ($i = 0; $i -lt 60; $i++) {
        if (Test-Port 8103) { $started = $true; break }
        if ($docMcpProc.HasExited) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $started) {
        Show-LogTail $docMcpErr
        Show-LogTail $docMcpLog
        Stop-ProcessTree $docMcpProc
        Stop-ProcessTree $frontendProc
        Stop-ProcessTree $backendProc
        throw 'Document MCP server did not start within 30s.'
    }
    Write-Host 'Document MCP OK.'
} else {
    Write-Host 'Document MCP already running on 8103.'
}

$demoLlmProc = $null
if (-not (Test-Port 8101)) {
    Write-Host 'Starting demo LLM server on http://127.0.0.1:8101/v1 ...'
    Remove-Item $demoLlmLog, $demoLlmErr -ErrorAction SilentlyContinue
    $demoLlmProc = Start-Process -FilePath $python `
        -ArgumentList @('demo_llm_server.py', '--host', '127.0.0.1', '--port', '8101') `
        -WorkingDirectory $backendDir -NoNewWindow `
        -RedirectStandardOutput $demoLlmLog -RedirectStandardError $demoLlmErr -PassThru
    $started = $false
    for ($i = 0; $i -lt 60; $i++) {
        if (Test-Port 8101) { $started = $true; break }
        if ($demoLlmProc.HasExited) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $started) {
        Show-LogTail $demoLlmErr
        Show-LogTail $demoLlmLog
        Stop-ProcessTree $demoLlmProc
        Stop-ProcessTree $docMcpProc
        Stop-ProcessTree $weatherMcpProc
        Stop-ProcessTree $demoMcpProc
        Stop-ProcessTree $frontendProc
        Stop-ProcessTree $backendProc
        throw 'Demo LLM server did not start within 30s.'
    }
    Write-Host 'Demo LLM OK.'
} else {
    Write-Host 'Demo LLM already running on 8101.'
}

# 6.5) Seed demo data (idempotent; needs the local MCP servers above to discover tools)
Write-Host 'Seeding demo data (MCP servers / Skills / Agents) ...'
Push-Location $backendDir
try {
    & $python -m app.db.seed
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Seed failed with exit code $LASTEXITCODE (services keep running)."
    }
} finally {
    Pop-Location
}

# 7) Open browser
if (-not $NoBrowser) {
    Start-Process 'http://localhost:5173'
}

Write-Host ''
Write-Host 'AgentHub is running:'
Write-Host '  Frontend: http://localhost:5173'
Write-Host '  Backend:  http://127.0.0.1:8001'
Write-Host '  API docs: http://127.0.0.1:8001/docs'
Write-Host '  Demo MCP: http://127.0.0.1:8100/mcp'
Write-Host '  Weather MCP: http://127.0.0.1:8102/mcp'
Write-Host '  Document MCP: http://127.0.0.1:8103/mcp'
Write-Host '  Demo LLM: http://127.0.0.1:8101/v1 (model: demo-chat)'
Write-Host "  Logs: $backendLog , $frontendLog"
Write-Host 'Press Ctrl+C to stop all services.'
Write-Host ''

# 8) Supervise
if (
    $backendProc -eq $null -and $frontendProc -eq $null -and
    $demoMcpProc -eq $null -and $weatherMcpProc -eq $null -and
    $docMcpProc -eq $null -and $demoLlmProc -eq $null
) {
    Write-Host 'All services were already running. Nothing to supervise.'
    exit 0
}

try {
    while ($true) {
        Start-Sleep -Seconds 2
        if ($backendProc -ne $null -and $backendProc.HasExited) {
            Write-Host 'Backend process exited.'
            break
        }
        if ($frontendProc -ne $null -and $frontendProc.HasExited) {
            Write-Host 'Frontend process exited.'
            break
        }
        if ($demoMcpProc -ne $null -and $demoMcpProc.HasExited) {
            Write-Host 'Demo MCP process exited.'
            break
        }
        if ($weatherMcpProc -ne $null -and $weatherMcpProc.HasExited) {
            Write-Host 'Weather MCP process exited.'
            break
        }
        if ($docMcpProc -ne $null -and $docMcpProc.HasExited) {
            Write-Host 'Document MCP process exited.'
            break
        }
        if ($demoLlmProc -ne $null -and $demoLlmProc.HasExited) {
            Write-Host 'Demo LLM process exited.'
            break
        }
    }
} finally {
    Stop-ProcessTree $frontendProc
    Stop-ProcessTree $backendProc
    Stop-ProcessTree $demoMcpProc
    Stop-ProcessTree $weatherMcpProc
    Stop-ProcessTree $docMcpProc
    Stop-ProcessTree $demoLlmProc
}
