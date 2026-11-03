param(
    [string]$VivadoPath = 'E:\sailingsi\Vivado\2020.2\bin\vivado.bat'
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $VivadoPath -PathType Leaf)) {
    throw "Vivado was not found: $VivadoPath"
}
$projectRoot = Split-Path -Parent $PSScriptRoot
$coreNames = @('rgb_to_gray', 'gray_filter_3x3', 'frame_equalize')
$rtlRoot = Join-Path $projectRoot 'rtl'
foreach ($coreName in $coreNames) {
    if (-not (Test-Path -LiteralPath (Join-Path $rtlRoot "$coreName.v") -PathType Leaf)) {
        throw "Required RTL source was not found: $coreName.v"
    }
}

# Vivado 2020.2 receives only ASCII paths; source and reports are copied
# without changing the originals. All three cores run in one serial flow.
$stageRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('codex_pfga_image_synth_' + [guid]::NewGuid().ToString('N'))
if ($stageRoot -match '[^\x00-\x7F]') {
    throw "Vivado requires an ASCII temporary path; current temporary folder is $stageRoot"
}
$finalOutput = Join-Path $projectRoot 'output\synthesis'
foreach ($folder in @('rtl', 'scripts')) {
    New-Item -ItemType Directory -Path (Join-Path $stageRoot $folder) -Force | Out-Null
}
Get-ChildItem -LiteralPath $rtlRoot -File |
    Where-Object { $_.Extension -in @('.v', '.sv') } |
    Copy-Item -Destination (Join-Path $stageRoot 'rtl')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'synthesize_image_cores.tcl') -Destination (Join-Path $stageRoot 'scripts\synthesize_image_cores.tcl')
New-Item -ItemType Directory -Path $finalOutput -Force | Out-Null
Write-Output "Synthesis folder: $stageRoot"
Write-Output 'Sequential out-of-context synthesis estimates only; no implementation or hardware download.'

$vivadoExit = -1
Push-Location -LiteralPath $stageRoot
try {
    & $VivadoPath -mode batch -notrace -source 'scripts/synthesize_image_cores.tcl' -log 'synthesis.log' -journal 'synthesis.jou'
    $vivadoExit = $LASTEXITCODE
}
finally {
    Pop-Location
    foreach ($logName in @('synthesis.log', 'synthesis.jou')) {
        $logPath = Join-Path $stageRoot $logName
        if (Test-Path -LiteralPath $logPath) {
            Copy-Item -LiteralPath $logPath -Destination (Join-Path $finalOutput $logName)
        }
    }
}
if ($vivadoExit -ne 0) {
    throw "Vivado synthesis failed with exit code $vivadoExit. See $finalOutput\synthesis.log"
}
$stageLog = Join-Path $stageRoot 'synthesis.log'
if (-not (Test-Path -LiteralPath $stageLog -PathType Leaf)) {
    throw 'Vivado did not create the synthesis log'
}
$logText = Get-Content -LiteralPath $stageLog -Raw
if ($logText -match '(?m)^CRITICAL WARNING:') {
    throw "Critical warnings remain in the current synthesis run. See $finalOutput\synthesis.log"
}
if ($logText -notmatch '(?m)^SYNTHESIS_ALL_OK estimates_only=1 cores=3 clock_period_ns=10\.000\s*$') {
    throw "The current synthesis run did not report its success marker. See $finalOutput\synthesis.log"
}

# Validate all staged results before replacing any final core reports.
foreach ($coreName in $coreNames) {
    if ($logText -notmatch "(?m)^SYNTH_CORE_OK $coreName\s*$") {
        throw "The current synthesis run did not complete $coreName"
    }
    $stagedCore = Join-Path $stageRoot "output\synthesis\$coreName"
    foreach ($name in @('utilization.rpt', 'timing_estimate.rpt', "${coreName}_synthesized.dcp")) {
        $artifact = Join-Path $stagedCore $name
        if (-not (Test-Path -LiteralPath $artifact -PathType Leaf)) {
            throw "Missing synthesis artifact: $artifact"
        }
    }
}
foreach ($coreName in $coreNames) {
    $stagedCore = Join-Path $stageRoot "output\synthesis\$coreName"
    $finalCore = Join-Path $finalOutput $coreName
    New-Item -ItemType Directory -Path $finalCore -Force | Out-Null
    Get-ChildItem -LiteralPath $stagedCore -File | Copy-Item -Destination $finalCore
}
Write-Output "SYNTHESIS_COMPLETED_ESTIMATES_ONLY: $finalOutput"
