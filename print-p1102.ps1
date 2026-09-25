param(
    [string]$Pdf,
    [int]$n = 1,
    [switch]$v,
    [switch]$DryRun,
    [switch]$Doctor,
    [switch]$ListDevices,
    [string]$Serial,
    [int]$Device
)
$root = $PSScriptRoot
$py = Get-Command python -EA SilentlyContinue
if (-not $py) { $py = Get-Command python3 -EA SilentlyContinue }
if (-not $py) { Write-Error "python not found"; exit 1 }
$a = @("$root\print_p1102.py")
if ($Doctor) { $a += "--doctor" }
elseif ($ListDevices) { $a += "--list-devices" }
else {
    if (-not $Pdf) { Write-Error "usage: print-p1102.ps1 file"; exit 1 }
    $a += $Pdf, "-n", $n
}
if ($v) { $a += "-v" }
if ($DryRun) { $a += "--dry-run" }
if ($Serial) { $a += "--serial", $Serial }
if ($Device) { $a += "--device", $Device }
& $py.Source @a
exit $LASTEXITCODE
