$ErrorActionPreference = "Stop"

$workspace = Split-Path -Parent $MyInvocation.MyCommand.Path
$dashboard = Join-Path $workspace "ForestFireDashboard-main"
$logDirectory = Join-Path $workspace "outputs"

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

function Test-Port {
    param([int]$Port)

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $connection = $client.ConnectAsync("127.0.0.1", $Port)
        return $connection.Wait(500) -and $client.Connected
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Start-DashboardProcess {
    param(
        [string]$Name,
        [int]$Port,
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory,
        [string]$LogName
    )

    if (Test-Port -Port $Port) {
        Write-Host "$Name is already running on port $Port."
        return
    }

    Start-Process `
        -FilePath $FilePath `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory `
        -RedirectStandardOutput (Join-Path $logDirectory "$LogName.log") `
        -RedirectStandardError (Join-Path $logDirectory "$LogName.err.log") `
        -WindowStyle Hidden | Out-Null

    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 1
        if (Test-Port -Port $Port) {
            Write-Host "$Name started on port $Port."
            return
        }
    }

    throw "$Name did not start. Check outputs\$LogName.err.log."
}

$npm = (Get-Command npm.cmd -ErrorAction Stop).Source
$python = (Get-Command python.exe -ErrorAction Stop).Source

Push-Location $dashboard
try {
    docker compose up -d
}
finally {
    Pop-Location
}

Start-DashboardProcess `
    -Name "Dashboard API" `
    -Port 3000 `
    -FilePath $npm `
    -ArgumentList @("start") `
    -WorkingDirectory (Join-Path $dashboard "server") `
    -LogName "dashboard_server"

Start-DashboardProcess `
    -Name "Prediction service" `
    -Port 5000 `
    -FilePath $python `
    -ArgumentList @("app.py") `
    -WorkingDirectory (Join-Path $workspace "Prediction") `
    -LogName "prediction_server"

Start-DashboardProcess `
    -Name "Burn severity service" `
    -Port 5001 `
    -FilePath $python `
    -ArgumentList @("app.py") `
    -WorkingDirectory (Join-Path $workspace "BurnedSeverity") `
    -LogName "burn_severity_server"

Start-DashboardProcess `
    -Name "Dashboard frontend" `
    -Port 5173 `
    -FilePath $npm `
    -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1") `
    -WorkingDirectory (Join-Path $dashboard "client") `
    -LogName "dashboard_client"

Write-Host ""
Write-Host "Dashboard ready: http://127.0.0.1:5173/"
