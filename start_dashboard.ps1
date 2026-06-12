$ErrorActionPreference = "Stop"

$workspace = Split-Path -Parent $MyInvocation.MyCommand.Path
$dashboard = Join-Path $workspace "apps\dashboard"
$logDirectory = Join-Path $workspace "outputs\logs"
$viirsLogDirectory = Join-Path $logDirectory "viirs"
$modisLogDirectory = Join-Path $logDirectory "modis"
$serviceLogDirectory = Join-Path $logDirectory "services"
$condaEnvironment = "bhutan-fire-detection"
$logRetentionDays = if ($env:BHUTAN_FIRE_LOG_RETENTION_DAYS) {
    [int]$env:BHUTAN_FIRE_LOG_RETENTION_DAYS
}
else {
    30
}
$logSessionStamp = Get-Date -Format "yyyyMMdd_HHmmss"

New-Item -ItemType Directory -Path $viirsLogDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $modisLogDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $serviceLogDirectory -Force | Out-Null

function Remove-ExpiredLogs {
    param(
        [string]$RootDirectory,
        [int]$RetentionDays
    )

    if ($RetentionDays -lt 1) {
        throw "BHUTAN_FIRE_LOG_RETENTION_DAYS must be at least 1."
    }

    $resolvedLogRoot = [IO.Path]::GetFullPath($logDirectory)
    $resolvedRoot = [IO.Path]::GetFullPath($RootDirectory)
    if (
        $resolvedRoot -ne $resolvedLogRoot -and
        -not $resolvedRoot.StartsWith(
            $resolvedLogRoot + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw "Refusing to clean logs outside $resolvedLogRoot."
    }

    $cutoff = (Get-Date).AddDays(-$RetentionDays)
    Get-ChildItem -LiteralPath $resolvedRoot -Recurse -Directory -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq "archive" } |
        ForEach-Object {
            Get-ChildItem -LiteralPath $_.FullName -Recurse -File -Force -ErrorAction SilentlyContinue |
                Where-Object { $_.LastWriteTime -lt $cutoff } |
                ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }
        }
}

function Archive-CurrentLog {
    param(
        [string]$Directory,
        [string]$LogName
    )

    $archiveDirectory = Join-Path $Directory "archive"
    New-Item -ItemType Directory -Path $archiveDirectory -Force | Out-Null

    foreach ($suffix in @(".log", ".err.log")) {
        $currentPath = Join-Path $Directory "$LogName$suffix"
        if (Test-Path -LiteralPath $currentPath) {
            $archivePath = Join-Path $archiveDirectory "$($LogName)_$logSessionStamp$suffix"
            Move-Item -LiteralPath $currentPath -Destination $archivePath -Force
        }
    }
}

Remove-ExpiredLogs -RootDirectory $logDirectory -RetentionDays $logRetentionDays

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
        [string]$ProcessLogDirectory,
        [string]$LogName
    )

    if (Test-Port -Port $Port) {
        Write-Host "$Name is already running on port $Port."
        return
    }

    Archive-CurrentLog -Directory $ProcessLogDirectory -LogName $LogName

    Start-Process `
        -FilePath $FilePath `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory `
        -RedirectStandardOutput (Join-Path $ProcessLogDirectory "$LogName.log") `
        -RedirectStandardError (Join-Path $ProcessLogDirectory "$LogName.err.log") `
        -WindowStyle Hidden | Out-Null

    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 1
        if (Test-Port -Port $Port) {
            Write-Host "$Name started on port $Port."
            return
        }
    }

    throw "$Name did not start. Check $ProcessLogDirectory\$LogName.err.log."
}

function Start-NrtAutomation {
    param([string]$PythonPath)

    $pidFile = Join-Path $workspace "outputs\viirs_nrt\realtime_worker.pid"
    if (Test-Path -LiteralPath $pidFile) {
        $existingPid = [int](Get-Content -LiteralPath $pidFile -Raw).Trim()
        $existingProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $existingPid" -ErrorAction SilentlyContinue
        if ($existingProcess -and $existingProcess.CommandLine -like "*auto_viirs_nrt_fire_detection.py*") {
            Write-Host "VIIRS NRT automation is already running as process $existingPid."
            return
        }
        Remove-Item -LiteralPath $pidFile -Force
    }

    Archive-CurrentLog -Directory $viirsLogDirectory -LogName "viirs_realtime"

    $process = Start-Process `
        -FilePath $PythonPath `
        -ArgumentList @(
            "pipelines\auto_viirs_nrt_fire_detection.py",
            "--interval-minutes", "15",
            "--lookback-hours", "24",
            "--max-granules", "200",
            "--dashboard-import"
        ) `
        -WorkingDirectory $workspace `
        -RedirectStandardOutput (Join-Path $viirsLogDirectory "viirs_realtime.log") `
        -RedirectStandardError (Join-Path $viirsLogDirectory "viirs_realtime.err.log") `
        -WindowStyle Hidden `
        -PassThru

    Start-Sleep -Seconds 2
    if ($process.HasExited) {
        throw "VIIRS NRT automation did not start. Check outputs\logs\viirs\viirs_realtime.err.log."
    }
    Write-Host "VIIRS NRT automation started as process $($process.Id)."
}

function Start-ModisNrtAutomation {
    param([string]$PythonPath)

    $pidFile = Join-Path $workspace "outputs\modis_nrt\realtime_worker.pid"
    if (Test-Path -LiteralPath $pidFile) {
        $existingPid = [int](Get-Content -LiteralPath $pidFile -Raw).Trim()
        $existingProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $existingPid" -ErrorAction SilentlyContinue
        if ($existingProcess -and $existingProcess.CommandLine -like "*auto_modis_nrt_fire_detection.py*") {
            Write-Host "MODIS NRT automation is already running as process $existingPid."
            return
        }
        Remove-Item -LiteralPath $pidFile -Force
    }

    Archive-CurrentLog -Directory $modisLogDirectory -LogName "modis_realtime"

    $process = Start-Process `
        -FilePath $PythonPath `
        -ArgumentList @(
            "pipelines\auto_modis_nrt_fire_detection.py",
            "--interval-minutes", "15",
            "--lookback-hours", "24",
            "--max-granules", "80",
            "--dashboard-import"
        ) `
        -WorkingDirectory $workspace `
        -RedirectStandardOutput (Join-Path $modisLogDirectory "modis_realtime.log") `
        -RedirectStandardError (Join-Path $modisLogDirectory "modis_realtime.err.log") `
        -WindowStyle Hidden `
        -PassThru

    Start-Sleep -Seconds 2
    if ($process.HasExited) {
        throw "MODIS NRT automation did not start. Check outputs\logs\modis\modis_realtime.err.log."
    }
    Write-Host "MODIS NRT automation started as process $($process.Id)."
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
    -ProcessLogDirectory $serviceLogDirectory `
    -LogName "dashboard_server"

Start-DashboardProcess `
    -Name "Prediction service" `
    -Port 5000 `
    -FilePath $python `
    -ArgumentList @("app.py") `
    -WorkingDirectory (Join-Path $workspace "services\prediction") `
    -ProcessLogDirectory $serviceLogDirectory `
    -LogName "prediction_server"

Start-DashboardProcess `
    -Name "Burn severity service" `
    -Port 5001 `
    -FilePath $python `
    -ArgumentList @("app.py") `
    -WorkingDirectory (Join-Path $workspace "services\burn_severity") `
    -ProcessLogDirectory $serviceLogDirectory `
    -LogName "burn_severity_server"

Start-DashboardProcess `
    -Name "Dashboard frontend" `
    -Port 5173 `
    -FilePath $npm `
    -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1") `
    -WorkingDirectory (Join-Path $dashboard "client") `
    -ProcessLogDirectory $serviceLogDirectory `
    -LogName "dashboard_client"

Start-NrtAutomation -PythonPath $python
Start-ModisNrtAutomation -PythonPath $python

Write-Host ""
Write-Host "Dashboard ready: http://127.0.0.1:5173/"
