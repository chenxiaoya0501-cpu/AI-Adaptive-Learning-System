$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Target = "D:\AI-Adaptive-Learning-System"
$RepositoryZip = "https://github.com/chenxiaoya0501-cpu/AI-Adaptive-Learning-System/archive/refs/heads/main.zip"
$TaskName = "AI-Adaptive-Learning-System"
$Port = 8000

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

Write-Step "Checking server resources"
$os = Get-CimInstance Win32_OperatingSystem
$freeMemoryGb = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
$drive = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='D:'"
$freeDiskGb = [math]::Round($drive.FreeSpace / 1GB, 2)
Write-Host "Free memory: $freeMemoryGb GB; D: free disk: $freeDiskGb GB"
if ($freeDiskGb -lt 10) { throw "D: must have at least 10 GB free" }

Write-Step "Preparing isolated target directory"
New-Item -ItemType Directory -Path $Target -Force | Out-Null
$existing = @(Get-ChildItem -LiteralPath $Target -Force)
if ($existing.Count -gt 0 -and -not (Test-Path "$Target\.deployment-marker")) {
    throw "$Target is not empty and was not created by this deployment script. No files were changed."
}

$tempRoot = Join-Path $env:TEMP "adaptive-learning-deploy"
if (Test-Path $tempRoot) { Remove-Item -LiteralPath $tempRoot -Recurse -Force }
New-Item -ItemType Directory -Path $tempRoot | Out-Null

Write-Step "Downloading application source"
$zipPath = Join-Path $tempRoot "source.zip"
Invoke-WebRequest -Uri $RepositoryZip -OutFile $zipPath -UseBasicParsing
Expand-Archive -LiteralPath $zipPath -DestinationPath $tempRoot -Force
$sourceRoot = Get-ChildItem -LiteralPath $tempRoot -Directory | Where-Object Name -Like "AI-Adaptive-Learning-System-*" | Select-Object -First 1
if (-not $sourceRoot) { throw "Downloaded source archive is invalid" }

if ((Get-ChildItem -LiteralPath $Target -Force).Count -gt 0) {
    Get-ChildItem -LiteralPath $Target -Force | Remove-Item -Recurse -Force
}
Copy-Item -Path "$($sourceRoot.FullName)\*" -Destination $Target -Recurse -Force
New-Item -ItemType File -Path "$Target\.deployment-marker" -Force | Out-Null

Write-Step "Preparing Python runtime"
$python = "D:\python311\python.exe"
if (-not (Test-Path $python)) { throw "Expected Python 3.11 at D:\python311\python.exe" }
& $python -m pip --version
if ($LASTEXITCODE -ne 0) {
    throw "The existing Python 3.11 installation does not include pip"
}
$runtimePackages = "$Target\.runtime\python-packages"
New-Item -ItemType Directory -Path $runtimePackages -Force | Out-Null
& $python -m pip install --upgrade --target $runtimePackages -r "$Target\apps\backend\requirements-demo.txt"
if ($LASTEXITCODE -ne 0) { throw "Could not install backend dependencies" }

Write-Step "Installing prebuilt frontends"
$studentPrebuilt = "$Target\deploy\prebuilt\student"
$adminPrebuilt = "$Target\deploy\prebuilt\admin"
if (-not (Test-Path "$studentPrebuilt\index.html") -or -not (Test-Path "$adminPrebuilt\index.html")) {
    throw "Prebuilt frontend files are missing from the deployment package"
}
New-Item -ItemType Directory -Path "$Target\apps\frontend\student\dist" -Force | Out-Null
New-Item -ItemType Directory -Path "$Target\apps\frontend\admin\dist" -Force | Out-Null
Copy-Item -Path "$studentPrebuilt\*" -Destination "$Target\apps\frontend\student\dist" -Recurse -Force
Copy-Item -Path "$adminPrebuilt\*" -Destination "$Target\apps\frontend\admin\dist" -Recurse -Force

Write-Step "Registering Windows startup task"
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
$launcherPath = "$Target\.runtime\start-demo.cmd"
$launcher = @(
    "@echo off",
    "set `"PYTHONPATH=$runtimePackages`"",
    "cd /d `"$Target\apps\backend`"",
    "`"$python`" -m uvicorn app.demo:app --host 0.0.0.0 --port $Port"
)
Set-Content -LiteralPath $launcherPath -Value $launcher -Encoding Ascii
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$launcherPath`"" -WorkingDirectory "$Target\apps\backend"
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Description "AI adaptive learning demo" | Out-Null

if (-not (Get-NetFirewallRule -DisplayName $TaskName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $TaskName -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow | Out-Null
}
Start-ScheduledTask -TaskName $TaskName

Write-Step "Verifying service"
$deadline = (Get-Date).AddMinutes(2)
do {
    Start-Sleep -Seconds 3
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 5
        if ($health.status -eq "ok") { break }
    } catch {}
} while ((Get-Date) -lt $deadline)
if (-not $health -or $health.status -ne "ok") { throw "Service did not pass its health check" }

Write-Host "`nDeployment completed." -ForegroundColor Green
Write-Host "Student: http://47.98.38.178:$Port/"
Write-Host "Admin:   http://47.98.38.178:$Port/admin"
Write-Host "If the public URL is blocked, add TCP port $Port to the ECS security group."
