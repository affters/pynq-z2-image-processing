param(
    [string]$VivadoBin = 'E:\sailingsi\Vivado\2020.2\bin',
    [string]$PythonPath = 'python'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$referenceScript = Join-Path $PSScriptRoot 'gray_reference.py'
$stageRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('codex_pfga_gray_' + [guid]::NewGuid().ToString('N'))
$vectorDirectory = Join-Path $stageRoot 'vectors'
$finalOutput = Join-Path $projectRoot 'output\gray'
foreach ($folder in @('rtl', 'sim', 'vectors')) {
    New-Item -ItemType Directory -Path (Join-Path $stageRoot $folder) -Force | Out-Null
}
New-Item -ItemType Directory -Path $finalOutput -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot 'rtl\rgb_to_gray.v') -Destination (Join-Path $stageRoot 'rtl\rgb_to_gray.v')
Copy-Item -LiteralPath (Join-Path $projectRoot 'sim\tb_rgb_to_gray.sv') -Destination (Join-Path $stageRoot 'sim\tb_rgb_to_gray.sv')
Write-Output "Simulation folder: $stageRoot"
& $PythonPath $referenceScript prepare $vectorDirectory
if ($LASTEXITCODE -ne 0) { throw 'RGB fixture generation failed' }

function Invoke-GraySimTool {
    param([string]$ToolPath, [string[]]$ToolArguments)
    & $ToolPath @ToolArguments
    if ($LASTEXITCODE -ne 0) { throw "Simulation tool failed: $ToolPath (exit $LASTEXITCODE)" }
}

Push-Location -LiteralPath $vectorDirectory
try {
    Invoke-GraySimTool -ToolPath (Join-Path $VivadoBin 'xvlog.bat') -ToolArguments @('--sv', '../rtl/rgb_to_gray.v', '../sim/tb_rgb_to_gray.sv')
    Invoke-GraySimTool -ToolPath (Join-Path $VivadoBin 'xelab.bat') -ToolArguments @('tb_rgb_to_gray', '-s', 'gray_sim')
    Invoke-GraySimTool -ToolPath (Join-Path $VivadoBin 'xsim.bat') -ToolArguments @('gray_sim', '-runall', '-log', 'xsim.log')
    if ((Get-Content -LiteralPath '.\xsim.log' -Raw) -notmatch 'SIM_PASS rgb_to_gray count=') {
        throw 'Simulation did not report its pass marker'
    }
}
finally {
    Pop-Location
    foreach ($logName in @('xvlog.log', 'xelab.log', 'xsim.log')) {
        $logPath = Join-Path $vectorDirectory $logName
        if (Test-Path -LiteralPath $logPath) {
            Copy-Item -LiteralPath $logPath -Destination (Join-Path $finalOutput $logName)
        }
    }
}
& $PythonPath $referenceScript verify $vectorDirectory $finalOutput
if ($LASTEXITCODE -ne 0) { throw 'Independent grayscale verification failed' }
Write-Output "Simulation and reference comparison completed: $finalOutput"
