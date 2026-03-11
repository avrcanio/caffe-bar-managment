$ErrorActionPreference = "Stop"

$msixUrl = "https://mozart.sibenik1983.hr/download/RunDesk.Client_1.4.7.0_x64.msix"
$msixPath = Join-Path $env:TEMP "RunDesk.Client_1.4.7.0_x64.msix"

Write-Host "Downloading RunDesk MSIX..." -ForegroundColor Cyan
Invoke-WebRequest -Uri $msixUrl -OutFile $msixPath -UseBasicParsing

Write-Host "Installing RunDesk MSIX..." -ForegroundColor Cyan
Add-AppxPackage -Path $msixPath -ForceUpdateFromAnyVersion

Write-Host "RunDesk installation completed." -ForegroundColor Green
