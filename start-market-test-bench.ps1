$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$Port = 8787
$HostName = "127.0.0.1"
$Url = "http://$HostName`:$Port"
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

function Resolve-PythonCommand {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        return @("py", "-3")
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return @("python")
    }

    $python3 = Get-Command python3 -ErrorAction SilentlyContinue
    if ($python3) {
        return @("python3")
    }

    throw "Python was not found. Please install Python 3.11 or newer and try again."
}

function Test-ServerReady {
    param([string]$TargetUrl)
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "$TargetUrl/api/health" -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Stop-ExistingMarketTestBenchServer {
    try {
        $connection = Get-NetTCPConnection -LocalAddress $HostName -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $connection) {
            return
        }

        $process = Get-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue
        if (-not $process) {
            return
        }

        $commandLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $($process.Id)").CommandLine
        if ($commandLine -and $commandLine.Contains("market_test_bench.cli")) {
            Stop-Process -Id $process.Id -Force
            Start-Sleep -Seconds 1
        }
    } catch {
        Write-Host "Could not stop the existing MarketTestBench server. Continuing with startup."
    }
}

if (-not (Test-Path $VenvPython)) {
    $PythonCommand = @(Resolve-PythonCommand)
    if ($PythonCommand.Length -gt 1) {
        & $PythonCommand[0] @($PythonCommand[1..($PythonCommand.Length - 1)]) -m venv .venv
    } else {
        & $PythonCommand[0] -m venv .venv
    }
}

& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -e .

Stop-ExistingMarketTestBenchServer
Start-Process -WindowStyle Hidden -FilePath $VenvPython -ArgumentList @(
    "-m", "market_test_bench.cli", "serve", "--host", $HostName, "--port", "$Port"
) -WorkingDirectory $ProjectRoot

for ($i = 0; $i -lt 30; $i++) {
    if (Test-ServerReady $Url) {
        Start-Process $Url
        exit 0
    }
    Start-Sleep -Seconds 1
}

Write-Host "MarketTestBench server could not be started."
Write-Host "Try running: .venv\Scripts\python.exe -m market_test_bench.cli serve"
Read-Host "Press Enter to close"
exit 1
