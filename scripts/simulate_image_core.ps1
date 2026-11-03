param(
    [ValidateSet('window', 'equalize')][string]$Kind = 'window',
    [ValidateRange(0, 3)][int]$Mode = 1,
    [int]$Width = 128,
    [int]$Height = 96,
    [string]$VivadoBin = 'E:\sailingsi\Vivado\2020.2\bin',
    [string]$PythonPath = 'python'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$coreName = if ($Kind -eq 'window') { 'gray_filter_3x3' } else { 'frame_equalize' }
$caseName = "${Kind}_m${Mode}_${Width}x${Height}"
$stageRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('codex_pfga_' + $caseName + '_' + [guid]::NewGuid().ToString('N'))
$vectorDirectory = Join-Path $stageRoot 'vectors'
$finalOutput = Join-Path $projectRoot "output\filters\$caseName"
foreach ($folder in @('rtl', 'sim', 'vectors')) {
    New-Item -ItemType Directory -Path (Join-Path $stageRoot $folder) -Force | Out-Null
}
New-Item -ItemType Directory -Path $finalOutput -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot "rtl\$coreName.v") -Destination (Join-Path $stageRoot "rtl\$coreName.v")
Copy-Item -LiteralPath (Join-Path $projectRoot "sim\tb_$coreName.sv") -Destination (Join-Path $stageRoot "sim\tb_$coreName.sv")
$wrapper = "``timescale 1ns/1ps`nmodule tb_image_case; tb_$coreName #(.IMAGE_WIDTH($Width), .IMAGE_HEIGHT($Height)) test(); endmodule`n"
[System.IO.File]::WriteAllText((Join-Path $stageRoot 'sim\tb_image_case.sv'), $wrapper, [System.Text.Encoding]::ASCII)
Write-Output "SIM_CASE=$caseName"
Write-Output "Simulation folder: $stageRoot"
& $PythonPath (Join-Path $PSScriptRoot 'filter_reference.py') prepare $vectorDirectory --kind $Kind --mode $Mode --width $Width --height $Height
if ($LASTEXITCODE -ne 0) { throw 'Fixture generation failed' }
function Invoke-ImageSimTool {
    param([string]$ToolPath, [string[]]$ToolArguments)
    & $ToolPath @ToolArguments
    if ($LASTEXITCODE -ne 0) { throw "Simulation tool failed: $ToolPath (exit $LASTEXITCODE)" }
}
Push-Location -LiteralPath $vectorDirectory
try {
    Invoke-ImageSimTool -ToolPath (Join-Path $VivadoBin 'xvlog.bat') -ToolArguments @('--sv', "../rtl/$coreName.v", "../sim/tb_$coreName.sv", '../sim/tb_image_case.sv')
    Invoke-ImageSimTool -ToolPath (Join-Path $VivadoBin 'xelab.bat') -ToolArguments @('tb_image_case', '-s', 'image_sim', '-mt', '2')
    Invoke-ImageSimTool -ToolPath (Join-Path $VivadoBin 'xsim.bat') -ToolArguments @('image_sim', '-runall', '-log', 'xsim.log')
    if ((Get-Content -LiteralPath '.\xsim.log' -Raw) -notmatch "SIM_PASS $coreName count=") {
        throw 'Simulation pass marker not found'
    }
}
finally {
    Pop-Location
    foreach ($logName in @('xvlog.log', 'xelab.log', 'xsim.log')) {
        $logPath = Join-Path $vectorDirectory $logName
        if (Test-Path -LiteralPath $logPath) { Copy-Item -LiteralPath $logPath -Destination (Join-Path $finalOutput $logName) }
    }
}
& $PythonPath (Join-Path $PSScriptRoot 'filter_reference.py') verify $vectorDirectory --output $finalOutput
if ($LASTEXITCODE -ne 0) { throw 'Independent result comparison failed' }
Write-Output "CASE_PASS=$caseName"
