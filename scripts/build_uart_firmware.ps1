[CmdletBinding()]
param(
    [ValidateSet(115200,1000000,2000000)][int]$BaudRate=115200,
    [string]$SourceDirectory,
    [string]$VivadoBin='E:\sailingsi\Vivado\2020.2\bin'
)
$ErrorActionPreference='Stop'
$uartRepo=Split-Path $PSScriptRoot -Parent
$uartSource=if ($SourceDirectory) {(Resolve-Path -LiteralPath $SourceDirectory).Path} else {Join-Path $uartRepo 'firmware\uart_image'}
$uartLlvm=Join-Path (Split-Path $VivadoBin -Parent) 'tps\llvm\7.0\win64\bin'
$uartOutput=Join-Path $uartRepo ('output\uart_firmware\build_'+[DateTime]::UtcNow.ToString('yyyyMMdd_HHmmss')+'_utc_'+[Guid]::NewGuid().ToString('N').Substring(0,8))
foreach ($uartName in @('start.S','main.c','link.ld')) {
    if (!(Test-Path -LiteralPath (Join-Path $uartSource $uartName))) {throw ('Missing firmware source '+$uartName)}
}
New-Item -ItemType Directory -Path $uartOutput -ErrorAction Stop | Out-Null
$uartBuildLog=Join-Path $uartOutput 'build.log'
$uartBase=@('--target=arm-none-eabi','-mcpu=cortex-a9','-marm','-mfloat-abi=soft','-ffreestanding')
& (Join-Path $uartLlvm 'clang.exe') @uartBase -c (Join-Path $uartSource 'start.S') -o (Join-Path $uartOutput 'start.o') 2>&1 | Tee-Object -FilePath $uartBuildLog
if ($LASTEXITCODE -ne 0) {throw 'Startup assembly failed'}
& (Join-Path $uartLlvm 'clang.exe') @uartBase -O2 -fno-builtin -fno-stack-protector -fno-unwind-tables -fno-asynchronous-unwind-tables -Wall -Wextra "-DUART_BAUD=$BaudRate" -c (Join-Path $uartSource 'main.c') -o (Join-Path $uartOutput 'main.o') 2>&1 | Tee-Object -FilePath $uartBuildLog -Append
if ($LASTEXITCODE -ne 0) {throw 'Firmware C compilation failed'}
& (Join-Path $uartLlvm 'lld.exe') -flavor gnu -m armelf -T (Join-Path $uartSource 'link.ld') -o (Join-Path $uartOutput 'uart_image.elf') (Join-Path $uartOutput 'start.o') (Join-Path $uartOutput 'main.o') 2>&1 | Tee-Object -FilePath $uartBuildLog -Append
if ($LASTEXITCODE -ne 0) {throw 'Firmware link failed'}
$uartHashes=[ordered]@{}
foreach ($uartName in @('start.S','main.c','link.ld')) {$uartHashes[$uartName]=(Get-FileHash -LiteralPath (Join-Path $uartSource $uartName)).Hash}
[ordered]@{built_utc=[DateTime]::UtcNow.ToString('o');baudrate=$BaudRate;compiler='Clang 7.0.1 ARM-none-eabi';linker='LLD 7.0.1 GNU armelf';entry_expected='0x00100000';elf_path=(Join-Path $uartOutput 'uart_image.elf');elf_sha256=(Get-FileHash -LiteralPath (Join-Path $uartOutput 'uart_image.elf')).Hash;source_hashes=$uartHashes;hardware_test=$false;note='Compilation only; source baud behavior and real transport require board verification'} | ConvertTo-Json -Depth 5 | Out-File -LiteralPath (Join-Path $uartOutput 'manifest.json') -Encoding utf8NoBOM -NoClobber
Write-Output ('UART_FIRMWARE_BUILD='+$uartOutput)
