param(
    [string]$VivadoPath = 'E:\sailingsi\Vivado\2020.2\bin\vivado.bat'
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $VivadoPath -PathType Leaf)) {
    throw "Vivado was not found: $VivadoPath"
}
$projectRoot = Split-Path -Parent $PSScriptRoot
$rtlRoot = Join-Path $projectRoot 'rtl'
$coreNames = @('rgb_to_gray.v', 'gray_filter_3x3.v', 'frame_equalize.v', 'image_axis_core.v')
foreach ($coreName in $coreNames) {
    if (-not (Test-Path -LiteralPath (Join-Path $rtlRoot $coreName) -PathType Leaf)) {
        throw "Required RTL source was not found: $coreName"
    }
}

# The checked-in Tcl embeds the official PYNQ-Z2 PS7 preset and builds offline.
# Vivado 2020.2 only sees the ASCII staging path, never the Unicode workspace.
$stageRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('codex_pfga_image_system_' + [guid]::NewGuid().ToString('N'))
if ($stageRoot -match '[^\x00-\x7F]') {
    throw "Vivado requires an ASCII temporary path: $stageRoot"
}
$finalOutput = Join-Path $projectRoot 'output\image_system'
foreach ($folder in @('rtl', 'scripts', 'constraints')) {
    New-Item -ItemType Directory -Path (Join-Path $stageRoot $folder) -Force | Out-Null
}
foreach ($coreName in $coreNames) {
    Copy-Item -LiteralPath (Join-Path $rtlRoot $coreName) -Destination (Join-Path $stageRoot "rtl\$coreName")
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'build_image_system.tcl') -Destination (Join-Path $stageRoot 'scripts\build_image_system.tcl')
Copy-Item -LiteralPath (Join-Path $projectRoot 'constraints\image_system.xdc') -Destination (Join-Path $stageRoot 'constraints\image_system.xdc')
New-Item -ItemType Directory -Path $finalOutput -Force | Out-Null
$stagedOutput = Join-Path $stageRoot 'output\image_system'

$inputManifest = [ordered]@{
    part = 'xc7z020clg400-1'
    tool_version = '2020.2'
    fabric_clock_hz = 50000000
    stage_path = $stageRoot
    ps7_preset_source = 'https://github.com/Xilinx/PYNQ/blob/v2.7.0/boards/Pynq-Z2/petalinux_bsp/hardware_project/pynqz2.tcl'
    ps7_preset_git_blob = 'dd415eac9a19aeb5ec9341718c47a68f76204544'
    ps7_preset_upstream_sha256 = '0c193c72fcf504ce432d4866870b08d06e8dd88410125fe7b23aae8ee256147c'
    inputs = @(Get-ChildItem -LiteralPath (Join-Path $stageRoot 'rtl'), (Join-Path $stageRoot 'scripts'), (Join-Path $stageRoot 'constraints') -File | ForEach-Object {
        [ordered]@{ name = $_.Name; sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
    })
}
Write-Output "IMAGE_SYSTEM_STAGE=$stageRoot"
Write-Output 'Builds PS7/DDR + DMA + GPIO + image core only; no hardware download or SD/Flash write.'
$vivadoExit = -1
Push-Location -LiteralPath $stageRoot
try {
    & $VivadoPath -mode batch -notrace -source 'scripts/build_image_system.tcl' -log 'image_system.log' -journal 'image_system.jou'
    $vivadoExit = $LASTEXITCODE
}
finally {
    Pop-Location
    $diagnosticOutput = Join-Path $finalOutput 'last_build'
    New-Item -ItemType Directory -Path $diagnosticOutput -Force | Out-Null
    $inputManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $diagnosticOutput 'input_manifest.json') -Encoding ascii
    foreach ($logName in @('image_system.log', 'image_system.jou')) {
        $logPath = Join-Path $stageRoot $logName
        if (Test-Path -LiteralPath $logPath) {
            Copy-Item -LiteralPath $logPath -Destination (Join-Path $diagnosticOutput $logName)
        }
    }
    # Keep generated initialization and HWH inspectable even when a later run fails.
    if (Test-Path -LiteralPath $stagedOutput) {
        Get-ChildItem -LiteralPath $stagedOutput -File | Copy-Item -Destination $diagnosticOutput
    }
}
if ($vivadoExit -ne 0) {
    throw "Vivado build failed with exit code $vivadoExit. See $finalOutput\last_build\image_system.log"
}
$logText = Get-Content -LiteralPath (Join-Path $stageRoot 'image_system.log') -Raw
if ($logText -notmatch '(?m)^IMAGE_SYSTEM_BUILD_OK .* programmed=0\s*$') {
    throw 'The current run did not report a completed implementation.'
}
foreach ($name in @('image_system.bit', 'image_system.hwh', 'image_system.xsa', 'ps7_init.tcl', 'image_system_routed.dcp', 'timing_summary.rpt', 'drc.rpt', 'implementation_summary.txt')) {
    if (-not (Test-Path -LiteralPath (Join-Path $stagedOutput $name) -PathType Leaf)) {
        throw "Missing implementation artifact: $name"
    }
}
# Replace final deliverables only after checking this run's success and artifacts.
Get-ChildItem -LiteralPath $stagedOutput -File | Copy-Item -Destination $finalOutput
$inputManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $finalOutput 'input_manifest.json') -Encoding ascii
Copy-Item -LiteralPath (Join-Path $stageRoot 'image_system.log') -Destination (Join-Path $finalOutput 'image_system.log')
Write-Output "IMAGE_SYSTEM_IMPLEMENTED_NOT_PROGRAMMED=$finalOutput"
