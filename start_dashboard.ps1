$ErrorActionPreference = "Stop"

$workspace = Split-Path -Parent $MyInvocation.MyCommand.Path
$dashboard = Join-Path $workspace "ForestFireDashboard-main"
$logDirectory = Join-Path $workspace "outputs"
$condaEnvironment = "bhutan-fire-detection"

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

if ($env:BHUTAN_FIRE_PYTHON) {
    $python = (Resolve-Path -LiteralPath $env:BHUTAN_FIRE_PYTHON -ErrorAction Stop).Path
    $environmentPath = Split-Path -Parent $python
}
else {
    $condaCandidates = @(
        (Get-Command conda.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1),
        "C:\Users\Public\miniforge3\Scripts\conda.exe",
        (Join-Path $env:USERPROFILE "miniforge3\Scripts\conda.exe"),
        (Join-Path $env:USERPROFILE "anaconda3\Scripts\conda.exe")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique

    $conda = $condaCandidates | Select-Object -First 1
    if (-not $conda) {
        throw "Conda was not found. Create the '$condaEnvironment' environment from environment.yml first."
    }

    $environmentPaths = (& $conda env list --json | ConvertFrom-Json).envs
    $environmentPath = $environmentPaths |
        Where-Object { (Split-Path -Leaf $_) -eq $condaEnvironment } |
        Select-Object -First 1

    if (-not $environmentPath) {
        throw "Conda environment '$condaEnvironment' was not found. Run: conda env create -f environment.yml"
    }

    $python = Join-Path $environmentPath "python.exe"
}

$environmentBinaryPaths = @(
    $environmentPath,
    (Join-Path $environmentPath "Library\mingw-w64\bin"),
    (Join-Path $environmentPath "Library\usr\bin"),
    (Join-Path $environmentPath "Library\bin"),
    (Join-Path $environmentPath "Scripts"),
    (Join-Path $environmentPath "bin")
) | Where-Object { Test-Path -LiteralPath $_ }

$env:CONDA_DEFAULT_ENV = Split-Path -Leaf $environmentPath
$env:CONDA_PREFIX = $environmentPath
$env:GDAL_DATA = Join-Path $environmentPath "Library\share\gdal"
$env:PROJ_DATA = Join-Path $environmentPath "Library\share\proj"
$env:PROJ_LIB = $env:PROJ_DATA
$env:PATH = (($environmentBinaryPaths + $env:PATH) -join [IO.Path]::PathSeparator)

Write-Host "Python environment: $python"

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
