param(
    [string]$BuildDirectory = '',
    [string]$StageParent = '',
    [string]$VivadoBin = 'E:\sailingsi\Vivado\2020.2\bin',
    [string]$PythonPath = 'python'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (!$BuildDirectory) { $BuildDirectory = Join-Path $projectRoot 'output\image_system' }
$bitfile = Join-Path $BuildDirectory 'image_system.bit'
$hwhfile = Join-Path $BuildDirectory 'image_system.hwh'
$initfile = Join-Path $BuildDirectory 'ps7_init.tcl'
$xsafile = Join-Path $BuildDirectory 'image_system.xsa'
foreach ($path in @($bitfile, $hwhfile, $initfile, $xsafile)) {
    if (!(Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required build output missing: $path" }
}
# The debugger test has fixed, explicit MMIO addresses and frame dimensions.
# Refuse to touch hardware if a different overlay contract was supplied.
[xml]$hwh = Get-Content -LiteralPath $hwhfile -Raw
foreach ($item in @(@('axi_dma_0', '0x40400000'), @('axi_gpio_0', '0x41200000'))) {
    $entry = @($hwh.SelectNodes('//MEMRANGE') | Where-Object { $_.INSTANCE -eq $item[0] -and $_.BASEVALUE -eq $item[1] })
    if ($entry.Count -ne 1) { throw "HWH address mismatch: $($item[0])" }
}
$core = $hwh.SelectSingleNode('//MODULE[@INSTANCE="image_axis_core_0"]')
foreach ($item in @(@('IMAGE_WIDTH', '128'), @('IMAGE_HEIGHT', '96'))) {
    $entry = @($core.SelectNodes('.//PARAMETER') | Where-Object { $_.NAME -eq $item[0] -and $_.VALUE -eq $item[1] })
    if (!$entry.Count) { throw "HWH dimension mismatch: $($item[0])" }
}
$reset = $hwh.SelectSingleNode('//MODULE[@INSTANCE="rst_fclk0"]')
foreach ($item in @(@('C_EXT_RESET_HIGH', '0'), @('C_AUX_RESET_HIGH', '1'))) {
    $entry = @($reset.SelectNodes('.//PARAMETER') | Where-Object { $_.NAME -eq $item[0] -and $_.VALUE -eq $item[1] })
    if (!$entry.Count) { throw "HWH reset polarity mismatch: $($item[0]); rebuild the corrected system first" }
}
$runName = 'run_' + [DateTime]::UtcNow.ToString('yyyyMMdd_HHmmss') + '_utc'
$finalOutput = Join-Path $projectRoot "output\hardware\$runName"
if (Test-Path -LiteralPath $finalOutput) { throw 'Evidence run directory already exists' }
New-Item -ItemType Directory -Path $finalOutput | Out-Null
if (!$StageParent) { $StageParent = [IO.Path]::GetTempPath() }
if (!(Test-Path -LiteralPath $StageParent -PathType Container)) { throw 'StageParent must be an existing writable directory' }
$stage = Join-Path $StageParent ('codex_pfga_jtag_' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage | Out-Null
foreach ($path in @($bitfile, $hwhfile, $initfile, $xsafile, (Join-Path $PSScriptRoot 'test_image_system_jtag.tcl'))) {
    Copy-Item -LiteralPath $path -Destination $stage
}
$fixtures = Join-Path $stage 'fixtures'
& $PythonPath (Join-Path $PSScriptRoot 'hardware_reference.py') prepare $fixtures
if ($LASTEXITCODE -ne 0) { throw 'Fixture generation failed' }
$manifest = [ordered]@{ started_utc = [DateTime]::UtcNow.ToString('o'); build_directory = $BuildDirectory; files = @{} }
foreach ($path in @($bitfile, $hwhfile, $initfile, $xsafile, (Join-Path $PSScriptRoot 'test_image_system_jtag.tcl'))) {
    $leaf = Split-Path $path -Leaf
    $manifest.files[$leaf] = (Get-FileHash -LiteralPath (Join-Path $stage $leaf) -Algorithm SHA256).Hash
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $fixtures 'run_manifest.json') -Encoding utf8
function Test-LocalHardwarePort {
    $client = New-Object Net.Sockets.TcpClient
    try { return $client.ConnectAsync('127.0.0.1', 3121).Wait(1000) -and $client.Connected }
    catch { return $false }
    finally { $client.Dispose() }
}
if (!(Test-LocalHardwarePort)) {
    $serverPath = Join-Path $VivadoBin 'hw_server.bat'
    Start-Process -FilePath $serverPath -ArgumentList @('-stcp:127.0.0.1:3121', '-p0', '-I60') -WindowStyle Hidden | Out-Null
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    while (!(Test-LocalHardwarePort)) {
        if ([DateTime]::UtcNow -gt $deadline) { throw 'Local hw_server did not become ready' }
        Start-Sleep -Milliseconds 250
    }
}
Write-Output 'JTAG test: temporary FPGA configuration; CPUs halted; two volatile DDR buffers. No SD/QSPI writes.'
try {
    & (Join-Path $VivadoBin 'xsdb.bat') (Join-Path $stage 'test_image_system_jtag.tcl') (Join-Path $stage 'image_system.bit') (Join-Path $stage 'ps7_init.tcl') $fixtures (Join-Path $stage 'image_system.xsa') 2>&1 |
        Tee-Object -FilePath (Join-Path $fixtures 'jtag.log')
    if ($LASTEXITCODE -ne 0) { throw "XSDB failed with exit $LASTEXITCODE" }
    & $PythonPath (Join-Path $PSScriptRoot 'hardware_reference.py') verify $fixtures
    if ($LASTEXITCODE -ne 0) { throw 'Hardware output comparison failed' }
}
finally {
    Copy-Item -Path (Join-Path $fixtures '*') -Destination $finalOutput -Recurse
}
Write-Output "HARDWARE_EVIDENCE=$finalOutput"
