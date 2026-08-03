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
$pythonCandidates = @("D:\python311\python.exe", "python.exe", "py.exe")
$python = $null
foreach ($candidate in $pythonCandidates) {
    try {
        $resolved = Get-Command $candidate -ErrorAction Stop
        $python = $resolved.Source
        break
    } catch {}
}
if (-not $python) { throw "Python 3 was not found" }
$venvPython = "$Target\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { & $python -m venv "$Target\.venv" }
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r "$Target\apps\backend\requirements-demo.txt"

Write-Step "Preparing portable Node.js"
$nodeRoot = "$Target\.runtime\node"
$nodeExe = "$nodeRoot\node.exe"
if (-not (Test-Path $nodeExe)) {
    New-Item -ItemType Directory -Path "$Target\.runtime" -Force | Out-Null
    $nodeIndex = Invoke-WebRequest -Uri "https://nodejs.org/dist/latest-v20.x/" -UseBasicParsing
    $nodeFile = [regex]::Matches($nodeIndex.Content, 'node-v[0-9.]+-win-x64\.zip') | ForEach-Object Value | Select-Object -First 1
    if (-not $nodeFile) { throw "Could not locate the latest Node.js 20 archive" }
    $nodeZip = Join-Path $tempRoot $nodeFile
    Invoke-WebRequest -Uri "https://nodejs.org/dist/latest-v20.x/$nodeFile" -OutFile $nodeZip -UseBasicParsing
    Expand-Archive -LiteralPath $nodeZip -DestinationPath "$Target\.runtime" -Force
    $expandedNode = Get-ChildItem "$Target\.runtime" -Directory | Where-Object Name -Like "node-v*-win-x64" | Select-Object -First 1
    Move-Item -LiteralPath $expandedNode.FullName -Destination $nodeRoot
}
$env:Path = "$nodeRoot;$env:Path"

Write-Step "Building student and admin frontends"
Push-Location "$Target\apps\frontend\student"
& "$nodeRoot\npm.cmd" install --no-audit --no-fund
& "$nodeRoot\npm.cmd" run build
Pop-Location
Push-Location "$Target\apps\frontend\admin"
& "$nodeRoot\npm.cmd" install --no-audit --no-fund
& "$nodeRoot\npm.cmd" run build
Pop-Location

Write-Step "Registering Windows startup task"
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
$arguments = '-m uvicorn app.demo:app --host 0.0.0.0 --port ' + $Port
$action = New-ScheduledTaskAction -Execute $venvPython -Argument $arguments -WorkingDirectory "$Target\apps\backend"
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
