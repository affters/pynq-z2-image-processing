# 右侧 FPGA 实际图像分辨率升级记录（2026-11-03）

完整本轮回执见[hardware_qa.json](../evidence/provenance/res256_upgrade/hardware_qa.json)。348帧五模式会话正常停止后，已重新Start mode3锐化供用户观察，当前会话`output/uart_live/session_20261103_042144_094634dd`最后现场观察至frame131，约0.85验证帧/秒；仍运行、尚无最终result，因此不并入已完成会话统计。保留原始未修改GUI截图在`evidence/provenance/res256_upgrade/`，仅为本地证据，尚未发布或替代整机实物照片。

256×192 本地工作版本已完成实板 INFO、固定图案灰度、两幅固定输入各五模式、MF200 摄像头两帧各五模式验证。批处理的 21 次图像处理共核对 1,021,488 个输出像素，全部逐像素一致，错误像素数和最大绝对误差均为 0。随后完成的 GUI 有限会话另记录 348 帧、16,914,008 个输出像素，五种模式均已现场切换并正常 Stop，结果全部逐像素一致。两组测试分别统计，当前版本尚未形成新的最终冻结包或发布。

本记录覆盖的批处理证据截至 2026-11-03 04:10:40 UTC（北京时间 12:10:40），GUI 有限会话证据截至 04:18:25 UTC（北京时间 12:18:25）。本次记录核查只读取已有结果，不重新访问设备；批处理还核对了保存的数组。

## 实际像素与显示方式

| 项目 | 保留的 128×96 默认配置 | 显式选择的 256×192 配置 |
|---|---:|---:|
| FPGA RGB 输入宽×高 | 128×96 | 256×192 |
| 输入像素数 | 12,288 | 49,152 |
| RGB24 传输字节数 | 36,864 | 147,456 |
| mode 0 灰度、mode 4 直方图均衡输出 | 128×96，12,288 字节 | 256×192，49,152 字节 |
| mode 1 高斯、mode 2 Sobel、mode 3 锐化输出 | 126×94，11,844 字节 | 254×190，48,260 字节 |
| GUI 右图整数放大倍数 | 4 倍 | 2 倍 |

256 配置每个方向的输入像素数翻倍，实际输入及灰度/均衡输出像素数为旧配置的 **4 倍**。邻域模式使用有效 3×3 窗口，去掉四周一圈后输出 254×190。GUI 将真实输出按最近邻方式放大，灰度/均衡显示为 512×384，邻域模式显示为 508×380；这项显示操作本身不增加处理结果的像素或细节。

摄像头原始采集为 640×480，由电脑通过 OpenCV `INTER_AREA` 缩放并转为 RGB，实际送入 FPGA 的数组是 `[192,256,3]`。左侧可显示同一次采集的摄像头原图，右侧显示板端返回的实际数组。当前数据路径为“MF200 接电脑 → 串口发送 RGB → 板端 ARM/DMA/PL → 串口返回结果 → 电脑显示”，本次 `linux_test=false`、`sd_used=false`。

## 配对与加载证据

实际加载使用以下独立目录：

- 256 PL 构建目录（该历史或独立交付文件未收入本选集）
- 256 固件构建目录（该历史或独立交付文件未收入本选集）
- 本次编程记录目录（该历史或独立交付文件未收入本选集）

[build_pair.json](../output/uart_firmware/build_20261103_034121_utc_0bc11cf3/hardware_20261103_040821_utc_68d1d4c6/build_pair.json) 为 `pair_validated=true`、`validation_mode=manifest_bound`，尺寸为 256×192，身份为 `pynq_uart_image_256x192_v1`。该离线配对记录的 `hardware_access=false` 表示配对检查本身不接设备，实板结论来自后续加载日志及图像测试。

[load.log](../output/uart_firmware/build_20261103_034121_utc_0bc11cf3/hardware_20261103_040821_utc_68d1d4c6/load.log) 记录初始状态 `FPGA is not configured`，之后依次出现 `FPGA is configured`、`UART_IMAGE_PS_INIT_COMPLETE`、入口 `00100000` 和 `UART_IMAGE_FIRMWARE_STARTED`。[preflight.json](../output/uart_firmware/build_20261103_034121_utc_0bc11cf3/hardware_20261103_040821_utc_68d1d4c6/preflight.json) 记录串口 2,000,000 baud，未写 SD 或 Flash。

下列 SHA-256 已重新读取文件核对，与加载前清单和配对记录一致：

| 文件 | SHA-256 |
|---|---|
| [PL build_manifest.json](../output/image_system_256x192/build_20261103_034450_utc_787ac48d/build_manifest.json) | `724d386998a90b44e15ad66654d832f517aba436010be7e033561314a114faba` |
| [image_system.bit](../output/image_system_256x192/build_20261103_034450_utc_787ac48d/image_system.bit) | `5c5f834d520717ea27782cc4f84ba5b8339e02e11dc12eb4b0eaccea842f702e` |
| [uart_image.elf](../output/uart_firmware/build_20261103_034121_utc_0bc11cf3/uart_image.elf) | `9fb1becf183c475f5228062d576ecd684e0342af231dbcc24c090a6b1fc42ac9` |
| [ps7_init.tcl](../output/image_system_256x192/build_20261103_034450_utc_787ac48d/ps7_init.tcl) | `05ff63c18d43e9d8b6b117ab9e5463d76b8235266daec17327d23e09fecc788b` |

## 实板逐像素结果

四项测试均使用 `COM6`、2,000,000 baud、15 秒协议超时、显式 256×192 配置。每份结果均为 `requested_action_passed=true`、`error=null`、`cleanup_errors=[]`。INFO 只核对身份与尺寸，不计入图像处理次数。

| 测试及 result.json | 图像处理次数 | 核对输出像素 | 串口单次往返秒数 |
|---|---:|---:|---|
| [INFO](../output/uart_resolution/run_20261103_040835_utc_582b2e12/result.json) | 0 | 0 | INFO 0.015154 |
| [固定输入 1：mode 0](../output/uart_resolution/run_20261103_040847_utc_36f0b431/result.json) | 1 | 49,152 | 1.167821 |
| [固定输入 2 幅：各 mode 0～4](../output/uart_resolution/run_20261103_040921_utc_e4ddd36f/result.json) | 10 | 486,168 | 平均 1.164904，范围 1.161408～1.170741 |
| [MF200 采集 2 帧：各 mode 0～4](../output/uart_resolution/run_20261103_041022_utc_a5050e45/result.json) | 10 | 486,168 | 平均 1.164711，范围 1.161387～1.171133 |

两组五模式测试的像素数均为 `2 × (2 × 49,152 + 3 × 48,260) = 486,168`。所有图像用例均记录 `exact_match=true`、`independent_scalar_reference_match=true`、`mismatch_pixels=0`、`max_abs_error=0`，输出形状和传输字节数均匹配模式。相机批处理另记录 `camera_test=true`，选择的设备为 `MF200 Camera`，640×480 原始画面缩放为 256×192。

固定图 frame 0 含渐变、彩条、棋盘及黑白条纹，frame 1 为 RGB(128,128,128) 纯色。每幅输入在其五个模式间复用；相机两帧也分别在五个模式间复用，避免将不同画面误作同一输入比较。

保存结果已只读复核：输入 `.rgb` 字节数及 SHA-256、实际 `.gray` 和预期 `.gray` 字节一致性、返回 CRC32，以及 NPZ 中的实际/预期数组和输出形状均一致。完整 PNG、NPZ、RGB/灰度原始字节和逐例 metrics 随各测试目录保存。

| 输入 | RGB24 SHA-256 |
|---|---|
| 固定 frame 0 | `1e5645f2294223ed935112a6ca2a5e71c711f9fa955543890d995866b1c5fa0d` |
| 固定 frame 1 | `9a4fe3115b082f62e669785a652b8947553475ad4876e6672c2cf34c365b5ff0` |
| 相机 frame 0 | `a3f9b78eb501816c383f0cf5731979e59aac915aaed2e4d58628b0e0dfc1fe92` |
| 相机 frame 1 | `239b6369156f98206472df3c47a6eda47b644f71638edaa2c40c94acb4632ccf` |

输出 CRC32 以下均为八位十六进制，与实际保存的输出字节重新计算结果一致：

| 模式 | 固定 frame 0 | 固定 frame 1 | 相机 frame 0 | 相机 frame 1 |
|---|---|---|---|---|
| 0 gray | `8fad6707` | `f84ab9c1` | `074751b6` | `d32262b7` |
| 1 gaussian | `4bf235d1` | `0df29f81` | `f286f35d` | `3c56ceb9` |
| 2 sobel | `ef8a6b91` | `35452140` | `6249c919` | `d3c53b94` |
| 3 sharpen | `73db3f45` | `0df29f81` | `9cce8663` | `1ca7633b` |
| 4 equalize | `2197d397` | `f84ab9c1` | `700fdffb` | `7ade7c22` |

| result.json 所在运行目录 | 文件 SHA-256 |
|---|---|
| `run_20261103_040835_utc_582b2e12` | `4b34128f78e96c132831068caf494d07ec7d03b86f454dee23463f31b374d2fb` |
| `run_20261103_040847_utc_36f0b431` | `41ff3de67b1195489e9b879d27d25eec10742f17a42567dc885a466fa28d2751` |
| `run_20261103_040921_utc_e4ddd36f` | `8fbf41e5de462b722624f374794f474710a753bfbce5418cf666bbb5ffbcce6c` |
| `run_20261103_041022_utc_a5050e45` | `9b4ff9a4dee5ffc44c40edfb4c1ab2a15243e16460083d96ac1ecb6147e7cebf` |

当前约 **1.16 秒/次** 是 `uart_roundtrip_seconds`：包括串口请求/响应传输、ARM、DMA 与 PL 的联合处理；不包括相机采集、缩放、电脑参考计算或保存文件。该数值不能写成 PL 算法延迟、GUI 刷新帧率或摄像头采集帧率。

## GUI 五模式有限会话

现场已完成 mode 0～4 的切换并正常点击 Stop。[该 GUI 会话 result.json](../output/uart_live/session_20261103_041128_616ad4b7/result.json) 的 SHA-256 为 `d847d1a708f8f08f80d40004d05aa8189585d04d9932ac5c4338c7edfffc5528`，已重新读取核对。会话始于 2026-11-03 04:11:28.437417 UTC，结束并写盘于 04:18:25.220927 UTC；该记录与前述批处理 21 次完全分开。

| GUI 模式 | 已验证帧数 | 每帧实际输出宽×高 |
|---|---:|---:|
| 0 gray | 64 | 256×192 |
| 1 gaussian | 90 | 254×190 |
| 2 sobel | 71 | 254×190 |
| 3 sharpen | 53 | 254×190 |
| 4 equalize | 70 | 256×192 |
| 合计 | 348 | 16,914,008 个输出像素 |

已从 `cases` 重新核对 348 条连续帧编号、模式计数、输入/输出形状和请求/响应字节数，并重新计算像素总数。每条记录均为 `exact_match=true`、`mismatch_pixels=0`、`max_abs_error=0`；汇总为 `verified_modes=[0,1,2,3,4]`、`all_modes_verified=true`、`hardware_test=true`、`camera_test=true`、`error=null`、`cleanup_errors=[]`。固件身份为 `pynq_uart_image_256x192_v1`，MF200 原始采集 640×480，实际处理输入 256×192。

会话参数 `max_frames=0`、`frame_limit_reached=false`，本次结束来自现场 Stop 操作。此有限会话证明五种模式切换、逐帧校验和本次停止清理已完成；后续更长时间的运行应以各自会话记录为准。

逐帧 `verified_loop_frames_per_second` 的中位数为 **0.846026 帧/秒**，该验证循环包含采集、电脑参考计算、串口传输及保存开销。GUI 会话的串口往返平均 1.164640 秒，范围 1.160889～1.171475 秒。这两类指标的统计口径不同，均不能作为 PL 核心算法延迟。

主流程随后重新 Start 锐化模式进行持续观察；该新会话由主流程另行记录，本文不推断其累计帧数或最终结果。

## 重现加载与启动

先在现有 GUI 点击 Stop 并等待停止，释放串口和摄像头。重新加载 PL/固件之前，需要把**开发板**关电，确认红灯熄灭，等待 10 秒再上电；电脑无需重启。此免 SD 路径测试时，板上不插 TF 卡；PROG/UART 小 USB 接电脑，MF200 摄像头接电脑的 USB 大口。

加载器保留冷启动检查：如果初始 PL 已配置或状态不确定，会在改动设备之前拒绝继续，要求重新给开发板断电上电。正常重开 GUI 并连接现有固件不需要重复下载；断电后临时加载的程序失效，需要重新加载。以下命令需要与当前目录中已核实的这对 256 产物配合运行：

```powershell
$projectRoot = '.'
$py = Join-Path $projectRoot '.venv-uart\Scripts\python.exe'
$firmware = Join-Path $projectRoot 'output\uart_firmware\build_20261103_034121_utc_0bc11cf3'
$hardware = Join-Path $projectRoot 'output\image_system_256x192\build_20261103_034450_utc_787ac48d'

pwsh -NoProfile -File (Join-Path $projectRoot 'scripts\program_uart_firmware.ps1') -BuildDirectory $firmware -HardwareDirectory $hardware
```

加载成功后先独立 INFO，再启动 GUI；串口号应以当前电脑识别为准，本次为 COM6：

```powershell
& $py (Join-Path $projectRoot 'scripts\test_uart_resolution.py') --port COM6 --baud 2000000 --timeout 15 --width 256 --height 192 --info
& $py (Join-Path $projectRoot 'software\uart_live_demo.py') --port COM6 --baud 2000000 --timeout 15 --width 256 --height 192 --camera-name 'MF200 Camera' --mode 0
```

INFO 必须返回 `pynq_uart_image_256x192_v1` 和 256×192。确认 INFO 测试退出码为 0、`requested_action_passed=true` 后再运行下一行。GUI 点击 Start 开始采集，Stop 停止并释放设备；默认 `--max-frames 0` 持续运行。GUI 的模式选择只切换算法，分辨率由启动参数明确指定。

批处理复现可依次运行，逐项确认退出码为 0，并出现 `UART_RESOLUTION_VERIFY_PASS`；默认输出使用新建的唯一目录：

```powershell
$resolutionTest = Join-Path $projectRoot 'scripts\test_uart_resolution.py'
$uartArgs = @('--port','COM6','--baud','2000000','--timeout','15','--width','256','--height','192')
& $py $resolutionTest @uartArgs --source fixed --frames 1 --mode 0
& $py $resolutionTest @uartArgs --source fixed --frames 2 --mode all
& $py $resolutionTest @uartArgs --source camera --frames 2 --mode all --camera-name 'MF200 Camera'
```

运行批处理前应让 GUI 保持 Stop；批处理结束并关闭资源后再 Start GUI。串口验证失败、像素不一致或资源清理错误均使批处理返回非零退出码，不能根据部分成功用例判定整组通过。

## 兼容性与交付状态

生产 host、相机和 GUI 的默认配置仍为 128×96，身份仍为 `pynq_uart_image_v1`；256×192 通过 `--width 256 --height 192` 显式选择，必须同时加载匹配的 PL 和固件。INFO 尺寸、身份、长度不匹配即拒绝连接，避免混用新旧配置。批处理专用测试入口默认 256×192，上述重现命令仍显式写出尺寸。协议 32 字节头、magic 与 CRC 规则保留。

[host 离线验证记录](../evidence/provenance/res256_upgrade/host_resolution_qa.json) 保留旧协议 9 项、运行/停止/限帧 7 项、预览 3 组输入，以及新增分辨率 14 项检查；其 `not_board_tested` 状态仅描述当时的离线验证阶段。本记录新增的实板证据如上，未改写历史验证记录。

当前 256 升级属于本地工作版本。已有 frozen v5 包和公开远端保持原版本；本文不代表新版已发布、已形成最终冻结包或已提交比赛。GUI 五模式切换与正常 Stop 已由上述 348 帧有限会话记录；后续持续观察会话需单独归档，并检查截图和实物证据，再单独冻结新版产物及更新对应交付材料。
