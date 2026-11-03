param(
    [int]$Width = 128, [int]$Height = 96,
    [string]$VivadoBin = 'E:\sailingsi\Vivado\2020.2\bin',
    [string]$PythonPath = 'python'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$caseName = "axis_${Width}x${Height}"
$stageRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('codex_pfga_' + $caseName + '_' + [guid]::NewGuid().ToString('N'))
$vectors = Join-Path $stageRoot 'vectors'
$output = Join-Path $projectRoot "output\axis\$caseName"
foreach ($folder in @('rtl', 'sim', 'vectors')) {
    New-Item -ItemType Directory -Path (Join-Path $stageRoot $folder) -Force | Out-Null
}
New-Item -ItemType Directory -Path $output -Force | Out-Null
foreach ($name in @('rgb_to_gray', 'gray_filter_3x3', 'frame_equalize', 'image_axis_core')) {
    Copy-Item -LiteralPath (Join-Path $projectRoot "rtl\$name.v") -Destination (Join-Path $stageRoot 'rtl')
}
Copy-Item -LiteralPath (Join-Path $projectRoot 'sim\tb_image_axis_core.sv') -Destination (Join-Path $stageRoot 'sim')
$wrapper = "``timescale 1ns/1ps`nmodule tb_image_case; tb_image_axis_core #(.IMAGE_WIDTH($Width),.IMAGE_HEIGHT($Height)) test(); endmodule`n"
[IO.File]::WriteAllText((Join-Path $stageRoot 'sim\tb_image_case.sv'), $wrapper, [Text.Encoding]::ASCII)
& $PythonPath (Join-Path $PSScriptRoot 'axis_reference.py') prepare $vectors --width $Width --height $Height
if ($LASTEXITCODE -ne 0) { throw 'Fixture generation failed' }
function Invoke-SimTool([string]$Tool, [string[]]$ToolArguments) {
    & (Join-Path $VivadoBin $Tool) @ToolArguments
    if ($LASTEXITCODE -ne 0) { throw "Tool failed: $Tool" }
}
Push-Location -LiteralPath $vectors
try {
    Invoke-SimTool 'xvlog.bat' @('--sv', '../rtl/rgb_to_gray.v', '../rtl/gray_filter_3x3.v', '../rtl/frame_equalize.v', '../rtl/image_axis_core.v', '../sim/tb_image_axis_core.sv', '../sim/tb_image_case.sv')
    Invoke-SimTool 'xelab.bat' @('tb_image_case', '-s', 'axis_sim', '-mt', '2')
    Invoke-SimTool 'xsim.bat' @('axis_sim', '-runall', '-log', 'xsim.log')
    if ((Get-Content '.\xsim.log' -Raw) -notmatch 'SIM_PASS image_axis_core modes=5') { throw 'No AXIS pass marker' }
}
finally {
    Pop-Location
    foreach ($log in @('xvlog.log', 'xelab.log', 'xsim.log')) {
        if (Test-Path -LiteralPath (Join-Path $vectors $log)) { Copy-Item -LiteralPath (Join-Path $vectors $log) -Destination $output }
    }
}
& $PythonPath (Join-Path $PSScriptRoot 'axis_reference.py') verify $vectors --output $output
if ($LASTEXITCODE -ne 0) { throw 'Independent comparison failed' }
Write-Output "CASE_PASS=$caseName"
