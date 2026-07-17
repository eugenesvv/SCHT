param(
    [ValidateSet('reset', 'phase1', 'phase2', 'phase3')]
    [string]$Step = 'reset'
)

$root = Split-Path -Parent $PSScriptRoot
$fixture = Join-Path $root 'test_data\Route_Planner_Persistence_Debug.log'
$working = Join-Path $root 'test_data\Route_Planner_Persistence_Working.log'

if ($Step -eq 'reset') {
    Copy-Item -LiteralPath $fixture -Destination $working -Force
    Write-Output "Reset working route log: $working"
    exit 0
}

if (-not (Test-Path -LiteralPath $working)) {
    Copy-Item -LiteralPath $fixture -Destination $working -Force
}

$phaseNumber = switch ($Step) {
    'phase1' { 1 }
    'phase2' { 2 }
    'phase3' { 3 }
}
$phase = Join-Path $root "test_data\Route_Planner_Persistence_Phase_$phaseNumber.log"

Add-Content -LiteralPath $working -Value ([Environment]::NewLine)
Get-Content -LiteralPath $phase | Add-Content -LiteralPath $working
Write-Output "Appended $Step to: $working"
