# Temporary JTAG only. Caller must have the intended PYNQ-Z2 connected/powered.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$BuildDirectory,
    [string]$VivadoBin='E:\sailingsi\Vivado\2020.2\bin',
    [string]$HardwareDirectory
)
$ErrorActionPreference='Stop'
$uartRepo=Split-Path $PSScriptRoot -Parent
$uartBuild=(Resolve-Path -LiteralPath $BuildDirectory).Path
$uartManifest=Get-Content -LiteralPath (Join-Path $uartBuild 'manifest.json') -Raw | ConvertFrom-Json
$uartElf=Join-Path $uartBuild 'uart_image.elf'
if ((Get-FileHash -LiteralPath $uartElf).Hash -ne $uartManifest.elf_sha256) {throw 'Firmware manifest hash mismatch'}
$uartHardware=if ($HardwareDirectory) {(Resolve-Path -LiteralPath $HardwareDirectory).Path} else {Join-Path $uartRepo 'output\image_system'}
$uartBit=Join-Path $uartHardware 'image_system.bit'
$uartInit=Join-Path $uartHardware 'ps7_init.tcl'
if (!$HardwareDirectory -and (Get-FileHash -LiteralPath $uartBit).Hash -ne 'ebe2f73d9fd2d605629cb751a734b0da2db1341e9c1e7d21a415979a0a65f3eb') {throw 'Verified bitstream changed'}
if ((Get-FileHash -LiteralPath $uartInit).Hash -ne '05ff63c18d43e9d8b6b117ab9e5463d76b8235266daec17327d23e09fecc788b') {throw 'Matching PS initialization changed'}
$uartHw=Join-Path $uartBuild ('hardware_'+[DateTime]::UtcNow.ToString('yyyyMMdd_HHmmss')+'_utc_'+[Guid]::NewGuid().ToString('N').Substring(0,8))
New-Item -ItemType Directory -Path $uartHw -ErrorAction Stop | Out-Null
$uartPython=Join-Path $uartRepo '.venv-uart\Scripts\python.exe'
$uartPairArguments=@((Join-Path $PSScriptRoot 'check_uart_build_pair.py'),$uartBuild,$uartHardware,(Join-Path $uartHw 'build_pair.json'))
if (!$HardwareDirectory) {$uartPairArguments += '--legacy-pinned'}
& $uartPython @uartPairArguments
if ($LASTEXITCODE -ne 0) {throw 'Firmware/hardware profile pair rejected before hardware access'}
$uartPair=Get-Content -LiteralPath (Join-Path $uartHw 'build_pair.json') -Raw | ConvertFrom-Json
& $uartPython (Join-Path $PSScriptRoot 'check_uart_elf_layout.py') $uartElf (Join-Path $uartHw 'elf_layout.json')
if ($LASTEXITCODE -ne 0) {throw 'Firmware ELF layout rejected'}
$uartStage=Join-Path $env:TEMP ('pynq_uart_'+[Guid]::NewGuid().ToString('N'))
if ($uartStage -match '[^\x00-\x7F]') {throw 'Vivado requires an ASCII temporary staging path'}
New-Item -ItemType Directory -Path $uartStage -ErrorAction Stop | Out-Null
$uartFiles=[ordered]@{'image_system.bit'=$uartBit;'ps7_init.tcl'=$uartInit;'firmware.elf'=$uartElf;'load.tcl'=(Join-Path $PSScriptRoot 'load_uart_image.tcl')}
$uartHashes=[ordered]@{}
foreach ($uartName in $uartFiles.Keys) {
    Copy-Item -LiteralPath $uartFiles[$uartName] -Destination (Join-Path $uartStage $uartName)
    $uartHashes[$uartName]=(Get-FileHash -LiteralPath (Join-Path $uartStage $uartName)).Hash
    if ($uartHashes[$uartName] -ne (Get-FileHash -LiteralPath $uartFiles[$uartName]).Hash) {throw 'Staged input changed'}
    $uartPairExpected=if ($uartName -eq 'firmware.elf') {$uartPair.firmware_elf_sha256} elseif ($uartName -eq 'image_system.bit' -or $uartName -eq 'ps7_init.tcl') {$uartPair.artifacts.$uartName.sha256} else {$null}
    if ($uartPairExpected -and $uartHashes[$uartName] -ne $uartPairExpected) {throw 'Staged input differs from validated firmware/hardware pair'}
}
[ordered]@{created_utc=[DateTime]::UtcNow.ToString('o');stage=$uartStage;baudrate=$uartManifest.baudrate;image_width=$uartPair.image_width;image_height=$uartPair.image_height;firmware_info=$uartPair.firmware_info;pair_validation=$uartPair.validation_mode;hashes=$uartHashes;sd_write_performed=$false;flash_write_performed=$false;scope='Temporary FPGA plus ARM firmware load; transport/image validation is separate'} | ConvertTo-Json -Depth 4 | Out-File -LiteralPath (Join-Path $uartHw 'preflight.json') -Encoding utf8NoBOM -NoClobber
Start-Process -FilePath (Join-Path $VivadoBin 'hw_server.bat') -ArgumentList @('-stcp:127.0.0.1:3121','-p0','-I60') -WindowStyle Hidden
Start-Sleep -Seconds 2
& (Join-Path $VivadoBin 'xsdb.bat') (Join-Path $uartStage 'load.tcl') (Join-Path $uartStage 'image_system.bit') (Join-Path $uartStage 'ps7_init.tcl') (Join-Path $uartStage 'firmware.elf') 2>&1 | Tee-Object -FilePath (Join-Path $uartHw 'load.log')
if ((Get-Content -LiteralPath (Join-Path $uartHw 'load.log') -Raw) -notmatch 'UART_IMAGE_FIRMWARE_STARTED') {throw 'Firmware start marker absent; inspect load.log'}
Write-Output ('UART_FIRMWARE_PROGRAMMED='+$uartHw)
