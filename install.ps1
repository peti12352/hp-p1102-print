# irm https://raw.githubusercontent.com/peti12352/hp-p1102-print/main/install.ps1 | iex
$ErrorActionPreference = "Stop"
$Repo = if ($env:HP_P1102_REPO) { $env:HP_P1102_REPO } else { "https://github.com/peti12352/hp-p1102-print.git" }
$Root = if ($env:HP_P1102_HOME) { $env:HP_P1102_HOME } else { "$env:LOCALAPPDATA\hp-p1102-print" }
$Bin = "$env:LOCALAPPDATA\Programs\hp-p1102-print"

if (Test-Path "$PSScriptRoot\print_p1102.py") { $Root = $PSScriptRoot }
elseif (-not (Test-Path "$Root\.git")) { git clone --depth 1 $Repo $Root }
else { git -C $Root pull --ff-only 2>$null }

New-Item -ItemType Directory -Force -Path $Bin | Out-Null
Copy-Item "$Root\print_p1102.py","$Root\print-p1102.ps1" $Bin -Force
$path = [Environment]::GetEnvironmentVariable("Path", "User")
if ($path -notlike "*$Bin*") {
  [Environment]::SetEnvironmentVariable("Path", "$path;$Bin", "User")
}
$py = Get-Command python -EA SilentlyContinue
if (-not $py) { $py = Get-Command python3 -EA SilentlyContinue }
if (-not $py) { throw "python not found" }
& $py.Source "$Root\print_p1102.py" --doctor
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "installed: $Bin\print-p1102.ps1"
