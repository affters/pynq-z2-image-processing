# PYNQ-Z2 five-mode image processing — working code/evidence package

本包为2026-11-02冻结的匿名代码与代表性证据副本。没有发布公开仓库或向比赛系统上传。
官方DOCX报告、双语署名海报与完整系统正面/45°照片独立交付；本包不声称最终材料齐全。

已验证：128×96、50MHz；MF200接电脑采集/缩放，经2Mbps UART→裸机ARM→DDR/DMA→PL→UART回电脑。
五模式为灰度、Gaussian、Sobel、锐化、当前帧均衡；0/4输出128×96，其余126×94有效内区。
11月2日固定图及真实相机各10 cases、120216像素exact。GUI两会话9291帧(mode0/1)与750帧(mode2/3/4)全部exact，合计10041帧并合计覆盖五模式；各会话all_modes_verified=false保持不变。
约3.20fps是含PC采集、参考、UART与存图的验证循环速率。11月1日2299帧五模式及重开981帧mode4历史也保留。SD/Linux/PYNQ/Jupyter、板端USB采集、HDMI、功耗及30fps未通过。
本程序没有驱动LD0/LD1，灯灭不能判断图像结果。

## Layout

| Recommended role | Included paths |
|---|---|
| src | rtl/, firmware/, software/, constraints/ |
| sim | sim/, scripts/*reference.py, scripts/simulate*, output/gray, filters, axis |
| build | scripts/build_image_system.*, synthesize*, output/image_system, output/synthesis |
| board | scripts/program_uart_firmware.ps1, load_uart_image.tcl, output/uart_firmware |
| data | Selected complete fixed/camera batches in output/, selected provenance in evidence/ |
| skill | skill/ |
| report | report/technical_report.md, llm_logs/ |

## Dependencies and offline verification

Windows PowerShell 7、Vivado 2020.2（含ARM Clang/LLD7.0.1、XSim、XSDB）、Python3.12含Tk。
工具安装不随包分发。Python依赖固定于software/requirements_uart_host.txt（NumPy、Pillow、pyserial、OpenCV headless）。
先在包根目录运行下列只读离线检查，不接板也能执行；软件host检查只验证参考及错误清理，不替代硬件。

```powershell
python -m venv .venv-uart
$py = '.\.venv-uart\Scripts\python.exe'
& $py -m pip install -r .\software\requirements_uart_host.txt
& $py .\scripts\verify_submission_package_nov2.py
& $py .\scripts\check_uart_host_protocol.py
& $py .\scripts\check_software_reference.py
& $py .\scripts\check_driver_lifecycle.py
& $py .\scripts\check_uart_live_limits.py
```

manifest.json逐文件记录包SHA/长度及工作区源SHA/长度；转换项单列，原工作区证据保持不变。
historical_sha256是历史原件标识，不等于路径脱敏后字节SHA；对照JSON中的path/sha字段已指向本包副本，另保留source_original_sha256。
验证器重算历史115200/2M固定图、历史2M相机及11月2日固定图/相机批次的独立整数参考、原始NPZ和响应CRC，复算历史同输入事务中位数。五份GUI summary保留全部case；选择12个代表raw样本，不伪称完整逐帧数组已全部打包。

## Rebuild and run

将下列Vivado安装位置改为本机位置。仿真脚本显式传-PythonPath，综合/实现仅离线执行，不下载。
旧版工具要求TEMP为可写ASCII路径；若默认TEMP含非ASCII字符，请在本次终端为工具选择ASCII临时目录。

```powershell
$vb = 'C:\Xilinx\Vivado\2020.2\bin'
& .\scripts\simulate_rgb_to_gray.ps1 -VivadoBin $vb -PythonPath $py
& .\scripts\simulate_image_core.ps1 -Kind window -Mode 1 -Width 128 -Height 96 -VivadoBin $vb -PythonPath $py
& .\scripts\simulate_image_core.ps1 -Kind window -Mode 2 -Width 128 -Height 96 -VivadoBin $vb -PythonPath $py
& .\scripts\simulate_image_core.ps1 -Kind window -Mode 3 -Width 128 -Height 96 -VivadoBin $vb -PythonPath $py
& .\scripts\simulate_image_core.ps1 -Kind equalize -Mode 1 -Width 128 -Height 96 -VivadoBin $vb -PythonPath $py
& .\scripts\simulate_image_axis.ps1 -Width 128 -Height 96 -VivadoBin $vb -PythonPath $py
& .\scripts\build_image_system.ps1 -VivadoPath (Join-Path $vb 'vivado.bat')
& .\scripts\build_uart_firmware.ps1 -BaudRate 2000000 -VivadoBin $vb
```

构建输出新目录，不沿用旧硬件通过结论。旧115200源码在firmware/baselines/uart_115200，使用-BaudRate115200及-SourceDirectory重编。
两版已归档离线重编ELF与原硬件通过ELF逐字节相同，但重编本身没有再次上板。
当前原通过2M ELF SHA256为F60D7DBDB7D0983E76ACD46ED0AA59D28410240864CF7678BD51DDA9FA788328。

上板前关闭其他相机/串口程序，MF200接电脑，板卡PROG/UART接电脑；板卡全部供电断开后重新上电，确认PL未配置。
在普通非沙箱PowerShell/Vivado终端使用刚构建目录，核对实际FTDI串口后逐级运行。COM6仅为历史端口。
加载器拒绝已配置PL的热重载；已运行且只需再次Start时无需重新下载。不要绕过guard。

```powershell
$build = '.\output\uart_firmware\build_YYYYMMDD_HHMMSS_utc_ID'
& .\scripts\program_uart_firmware.ps1 -BuildDirectory $build -VivadoBin $vb
& $py .\software\uart_image_demo.py --port COM6 --baud 2000000 --info
& $py .\software\uart_image_demo.py --port COM6 --baud 2000000 --frames 1 --mode 0
& $py .\software\uart_image_demo.py --port COM6 --baud 2000000 --frames 2 --mode all
& $py .\software\uart_camera_demo.py --port COM6 --baud 2000000 --camera-name 'MF200 Camera' --frames 2 --mode all
& $py .\software\uart_live_demo.py --port COM6 --baud 2000000 --camera-name 'MF200 Camera'
```

预期INFO为pynq_uart_image_v1；两批各10case/120216像素exact，error=null且cleanup_errors=[]；GUI选择各模式后Stop，检查新会话结果。
模式1—3只比较有效内区。摄像头名称/VID0C45/PID6366须当次核对，避免选内置相机。
FPGA和ARM固件只临时JTAG加载，断电失效，不写SD/Flash。若重新实现bit发生变化，加载脚本固定hash会拒绝，需先独立核验新契约，不直接删hash检查。

## Evidence and limitations

output/uart_transport_comparison_20261101.json及docs/uart_transport_optimization.md对齐同输入/模式和同一PL实现：事务中位4.2839638→0.30025745秒，下降92.9911%，旧/新14.2676。
这是UART配置和ARM固件联合版本优化，PL资源沿用LUT3625/FF4014/BRAM6.5Tile/DSP0，非PL或CPU加速比，非资源减少。
每模式只有两幅固定图；历史host/loader逐run快照绑定不完整，不能宣称单因素实验或完整现场复原。
report/technical_report.md是匿名AMD七项要点设计报告阶段稿；仍缺完整系统照片、CPU/PL独立性能、功耗、公开仓库及提交核验。
llm_logs只包含匿名可见消息副本及真实工作摘要，不含系统/开发者/工具/内部推理，不是平台完整原始导出；图片保留文字引用。

原创代码MIT；PYNQ-Z2 PS7预设为BSD3-Clause，原完整声明见THIRD_PARTY_NOTICES.md。
AMD/Xilinx生成bit/HWH/XSA/初始化及报告沿用供应商条款，未把供应商IP或工具重新许可为MIT；工具安装/IP源码未打包。
本包仅本地评审准备，公开前还需核对适用的生成产物再分发条款、匿名上下文和最终材料。

## Nov2 evidence and bounded anonymous capture

The Nov2 fixed and camera batches are included in full. The two Nov2 GUI JSON
summaries retain all 10041 cases; one raw sample per represented mode/session is
selected. The separately recorded 10-frame mode4 capture supports the new
bounded Stop/save path and its real GUI screenshot, not another five-mode run.
Use `--max-frames 10` for a finite GUI capture; zero/default retains continuous
operation. Start remains explicit. UI evidence paths use relative project paths
or an external session name; original saved JSON paths are not changed by UI display.

`evidence/selection.json` declares every selected GUI sample and the bounded
capture. Complete per-frame GUI archives, private original screenshots, original
hardware-detail photos, DOCX and signed poster are excluded. New anonymous GUI
image bytes are preserved without generated reconstruction or image editing.

`output/test_resume_20261102.json` refers to packaged result hashes and retains
their original identifiers separately. Its private original screenshot record
is explicitly marked excluded. The Nov2 checkpoint's private-image and old
unselected-checkpoint links are plain exclusion notes in the package copy.
No numerical test result or original working-tree evidence is changed.

The visible LLM JSONL is a filtered snapshot with the exact counts and last
included timestamp declared below, not a complete platform export. Nov2
engineering results and the GUI capture change are documented by the dated
checkpoint and capture instructions.

Visible-message snapshot: 297 messages (96 user, 201 assistant); last included timestamp: 2026-11-02T13:01:54.048Z.
