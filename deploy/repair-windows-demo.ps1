$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Target = "D:\AI-Adaptive-Learning-System"
$Python = "D:\python311\python.exe"
$RuntimePackages = "$Target\.runtime\python-packages"
$TaskName = "AI-Adaptive-Learning-System"
$WatchdogTaskName = "$TaskName-Watchdog"
$Port = 8000
$RepositoryArchive = "https://codeload.github.com/chenxiaoya0501-cpu/AI-Adaptive-Learning-System/zip/refs/heads/main"

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python 3.11 was not found at $Python"
}
if (-not (Test-Path -LiteralPath "$Target\apps\backend")) {
    throw "The deployed application was not found at $Target"
}

Write-Step "Downloading the latest application files"
$TempRoot = Join-Path $env:TEMP "adaptive-learning-repair"
if (Test-Path -LiteralPath $TempRoot) {
    Remove-Item -LiteralPath $TempRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null
$ZipPath = Join-Path $TempRoot "source.zip"

& curl.exe -L --fail --retry 8 --retry-delay 2 $RepositoryArchive -o $ZipPath
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $ZipPath)) {
    throw "Could not download the latest application archive"
}

Expand-Archive -LiteralPath $ZipPath -DestinationPath $TempRoot -Force
$SourceRoot = Get-ChildItem -LiteralPath $TempRoot -Directory |
    Where-Object Name -Like "AI-Adaptive-Learning-System-*" |
    Select-Object -First 1
if (-not $SourceRoot) {
    throw "The downloaded application archive is invalid"
}

Write-Step "Updating application code without deleting existing data"
Copy-Item -Path "$($SourceRoot.FullName)\apps\backend\app" -Destination "$Target\apps\backend" -Recurse -Force
Copy-Item -Path "$($SourceRoot.FullName)\apps\backend\requirements-demo.txt" -Destination "$Target\apps\backend\requirements-demo.txt" -Force
Copy-Item -Path "$($SourceRoot.FullName)\deploy\prebuilt\student\*" -Destination "$Target\apps\frontend\student\dist" -Recurse -Force
Copy-Item -Path "$($SourceRoot.FullName)\deploy\prebuilt\admin\*" -Destination "$Target\apps\frontend\admin\dist" -Recurse -Force

Write-Step "Checking Python dependencies"
New-Item -ItemType Directory -Path $RuntimePackages -Force | Out-Null
& $Python -c "import sys; sys.path.insert(0, r'$RuntimePackages'); import easyocr, fitz, fastapi, sqlalchemy, uvicorn"
if ($LASTEXITCODE -ne 0) {
    Write-Host "A required package is missing; repairing dependencies..." -ForegroundColor Yellow
    & $Python -m pip install --ignore-installed --upgrade --target $RuntimePackages -r "$Target\apps\backend\requirements-demo.txt"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not repair Python dependencies"
    }
}

Write-Step "Creating a persistent background service"
$RuntimeDirectory = "$Target\.runtime"
New-Item -ItemType Directory -Path $RuntimeDirectory -Force | Out-Null
$LauncherPath = "$RuntimeDirectory\start_demo.py"
$Launcher = @"
import mimetypes
import sys
import time
import traceback
from pathlib import Path

target = Path(r"$Target")
runtime_packages = Path(r"$RuntimePackages")
log_path = target / ".runtime" / "server.log"
log = log_path.open("a", encoding="utf-8", buffering=1)
sys.stdout = log
sys.stderr = log
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
sys.path.insert(0, str(target / "apps" / "backend"))
sys.path.insert(0, str(runtime_packages))

import uvicorn

while True:
    try:
        uvicorn.run("app.demo:app", host="0.0.0.0", port=$Port, log_level="info")
    except BaseException:
        traceback.print_exc(file=log)
    print("Server process stopped; restarting in 5 seconds.", file=log, flush=True)
    time.sleep(5)
"@
Set-Content -LiteralPath $LauncherPath -Value $Launcher -Encoding UTF8

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $WatchdogTaskName -Confirm:$false -ErrorAction SilentlyContinue
$ExistingListener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($ExistingListener) {
    $ExistingListener |
        Select-Object -ExpandProperty OwningProcess -Unique |
        ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
}

$Action = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument "`"$LauncherPath`"" `
    -WorkingDirectory "$Target\apps\backend"
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 10 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Settings $Settings `
    -Description "Adaptive learning demo background service" |
    Out-Null

$WatchdogPath = "$RuntimeDirectory\watchdog.ps1"
$Watchdog = @"
`$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not `$listener) {
    `$task = Get-ScheduledTask -TaskName "$TaskName" -ErrorAction SilentlyContinue
    if (`$task) {
        if (`$task.State -eq "Running") {
            Stop-ScheduledTask -TaskName "$TaskName" -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
        }
        Start-ScheduledTask -TaskName "$TaskName" -ErrorAction SilentlyContinue
    }
}
"@
Set-Content -LiteralPath $WatchdogPath -Value $Watchdog -Encoding UTF8

$WatchdogAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$WatchdogPath`"" `
    -WorkingDirectory $RuntimeDirectory
$WatchdogTrigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
Register-ScheduledTask `
    -TaskName $WatchdogTaskName `
    -Action $WatchdogAction `
    -Trigger $WatchdogTrigger `
    -Principal $Principal `
    -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable) `
    -Description "Restarts the adaptive learning demo if port $Port stops listening" |
    Out-Null

if (-not (Get-NetFirewallRule -DisplayName $TaskName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule `
        -DisplayName $TaskName `
        -Direction Inbound `
        -Protocol TCP `
        -LocalPort $Port `
        -Action Allow |
        Out-Null
}

Start-ScheduledTask -TaskName $TaskName

Write-Step "Waiting for the application health check"
$Deadline = (Get-Date).AddMinutes(2)
$Healthy = $false
do {
    Start-Sleep -Seconds 3
    try {
        $Health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 5
        $Healthy = $Health.status -eq "ok"
    } catch {
        $Healthy = $false
    }
} while (-not $Healthy -and (Get-Date) -lt $Deadline)

if (-not $Healthy) {
    $LogTail = if (Test-Path -LiteralPath "$RuntimeDirectory\server.log") {
        (Get-Content -LiteralPath "$RuntimeDirectory\server.log" -Tail 40) -join "`n"
    } else {
        "No server log was created."
    }
    throw "The background service did not pass its health check.`n$LogTail"
}

Write-Host "`nREPAIR COMPLETED" -ForegroundColor Green
Write-Host "The service now runs in the background and survives remote desktop disconnection."
Write-Host "Student: http://47.98.38.178:$Port/"
Write-Host "Admin:   http://47.98.38.178:$Port/admin/"
