# FPGA多模式视觉处理与增强

v6更新于2026年11月3日。PYNQ-Z2（`xc7z020clg400-1`）使用Vivado 2020.2，当前演示处理256×192图像，保留128×96兼容配置。摄像头接电脑，图像经2Mbps UART、裸机ARM、DDR/DMA进入FPGA，五模式结果回传后逐像素验证；电脑还可从已验证Sobel输出提取平面零件外轮廓、标定并显示毫米估计值。

本次版本更新覆盖源码、[AMD七节设计报告](report/technical_report.md)、复现入口与选定证据。官方五部分模板Word/PDF和代码RAR分别交付，源码包与GitHub采用同一受审文件树；旧v5记录保留为历史。远端提交与下载核验由主流程完成后另记，不把本说明当作发布回执。公开仓库：[pynq-z2-image-processing](https://github.com/affters/pynq-z2-image-processing)。

## 当前功能与结果

| 项目 | v6实证及边界 |
|---|---|
| 五种FPGA模式 | 整数灰度、高斯去噪、Sobel边缘、锐化、当前帧全局直方图均衡；一次加载内运行时切换模式 |
| 256×192链路 | RGB24输入147456字节；灰度/均衡输出256×192，邻域输出254×190；位流、固件及INFO尺寸严格匹配 |
| 数值正确性 | 固定图和真实MF200各两帧×五模式、10次486168输出像素全部exact |
| 五模式GUI | 独立348帧全部exact、单会话五模式覆盖、正常Stop且运行/清理无错 |
| 处理与传输时间 | 256相机UART平均约1.165s；GUI验证循环中位数约0.846fps，包含采集、参考、串口及保存，不是PL核延迟或屏幕刷新率 |
| 新完整PL实现 | 50MHz，LUT3744、FF4035、BRAM18.5 Tile、DSP0，setup/hold裕量2.962/0.037ns，DRC错误0 |
| 尺寸估计 | 已验证FPGA Sobel → 电脑端ROI/最大外轮廓/旋转外接框 → 两点标定 → px/mm；没有新增FPGA尺寸核 |

摄像头原始采集为640×480，PL实际处理256×192，左侧原图预览不改变这个范围。128×96与256×192是显式选择的两套构建配置，当前没有任意分辨率热切换。更高分辨率保留更多细节，也增加UART负载；不能把旧128配置约3.2fps写成当前256速度。

测量只作演示估计。用户经直尺量出的独立50mm纸面直线在图中跨70.5px，比例为0.709219858156mm/px；标称40×20mm手画矩形测得约42.55×22.70mm，偏差约2.55/2.70mm（6.38%/13.48%）。其连续首30条校准记录含27有效、3截断，没有隐藏无效帧。H形零件取证帧估计78.72×58.87mm，但没有独立实测真值。首次以20mm短边标定得到约44.87mm长边的偏差也保留，未用已知尺寸强行改写输出。显示两位小数不代表0.01mm精度。

尺寸调试会话最终2690帧Sobel像素全部exact、正常Stop；几何状态为1867有效、735截断、88无轮廓，包含摆放、调参和不同标定。2690不是准确测量次数，也不与独立348帧五模式验收合并。[分辨率记录](docs/right_resolution_2026_11_03.md)、[测量记录](docs/part_measurement_2026_11_03.md)和[v6范围说明](docs/update_v6.md)提供证据索引。

## 数据路径与使用条件

`MF200 → 电脑采集/缩放 → UART → 裸机ARM → DDR/DMA → FPGA五模式 → UART → 电脑逐像素验证/显示`

毫米换算位于电脑端，只处理已经与独立整数参考一致的Sobel完成帧。勾选“轮廓/尺寸测量（电脑端）”自动选择Sobel；右图拖框设置ROI，“全图ROI”恢复。默认“连接断边”使用一次3×3闭运算，邻近文字被连入时可关闭；阈值和最小面积可调。无标定只显示px；输入实际参照长度并点击两个端点后才显示mm。

相机需固定、镜头正对测量平面，参照与零件处于同一深度。移动相机、焦距或平面后清除并重做标定。轮廓被ROI/图像裁切或没有轮廓时不输出有效尺寸；新参数不会沿用旧尺寸叠加，重新Start会清除标定和ROI。原始FPGA数组、测量JSON和叠加PNG分开保存。系统没有自动分类、孔径/三维尺寸、透视/畸变补偿或量具精度认证。

## 快速复现

需要Windows PowerShell、Python 3.12、Vivado 2020.2及其XSDB/编译工具，PYNQ-Z2通过PROG/UART接电脑，MF200也接电脑。UART端口和工具路径按本机实际值替换。先建立环境并运行无设备检查：

```powershell
python -m venv .venv-uart
$py = '.\.venv-uart\Scripts\python.exe'
& $py -m pip install -r .\software\requirements_uart_host.txt
& $py -m pip install lxml
& $py .\scripts\check_uart_host_protocol.py
& $py .\scripts\check_uart_live_limits.py
& $py .\scripts\check_camera_preview_contract.py
& $py .\scripts\check_uart_resolution_profiles.py
& $py .\scripts\check_part_measurement.py
& $py .\scripts\check_part_measurement_gui.py
```

源码中的host/GUI及一般构建入口默认仍为128×96、部分CLI默认波特率115200。以下显式传256×192与2Mbps，避免混用。完整实现和固件构建仅生成文件，不连接板卡：

```powershell
$vivado = 'C:\AMD\Vivado\2020.2\bin' # 按实际安装目录修改
& .\scripts\simulate_image_axis.ps1 -Width 256 -Height 192 -VivadoBin $vivado -PythonPath $py
& .\scripts\build_image_system.ps1 -Width 256 -Height 192 -VivadoPath "$vivado\vivado.bat"
& .\scripts\build_uart_firmware.ps1 -BaudRate 2000000 -Width 256 -Height 192 -VivadoBin $vivado
```

读取脚本打印的新目录，并核对HWH、清单、时序与哈希。下列路径是本次已验收产物；从零重建者换成自己的新目录：

```powershell
$hw = '.\output\image_system_256x192\build_20261103_034450_utc_787ac48d'
$fw = '.\output\uart_firmware\build_20261103_034121_utc_0bc11cf3'
& .\scripts\program_uart_firmware.ps1 -BuildDirectory $fw -HardwareDirectory $hw -VivadoBin $vivado
& $py .\scripts\test_uart_resolution.py --port COM6 --baud 2000000 --timeout 15 --width 256 --height 192 --info
& $py .\scripts\test_uart_resolution.py --port COM6 --baud 2000000 --timeout 15 --width 256 --height 192 --source fixed --frames 2 --mode all
& $py .\scripts\test_uart_resolution.py --port COM6 --baud 2000000 --timeout 15 --width 256 --height 192 --source camera --frames 2 --mode all --camera-name 'MF200 Camera'
& $py .\scripts\test_part_measurement_hardware.py --port COM6 --baud 2000000 --timeout 15 --width 256 --height 192
& $py .\software\uart_live_demo.py --port COM6 --baud 2000000 --timeout 15 --width 256 --height 192 --camera-name 'MF200 Camera' --mode 2 --max-frames 0
```

加载前须让其他程序正常Stop并释放相机/串口，开发板断电后重新上电。加载器会在改动设备前拒绝已配置PL的热重载，不能绕过；bit和ELF临时加载、断电失效，不写SD/QSPI/eFUSE。运行阶段逐步检查INFO、完整帧CRC/尺寸、actual/expected和清理状态；批处理完成后再开启GUI。仅INFO成功不计为图像通过。

## 目录与证据

| 目录 | 内容 |
|---|---|
| `rtl/`、`constraints/`、`sim/` | 原创像素核、系统核、约束和测试台 |
| `firmware/` | 裸机ARM程序及历史115200基线 |
| `software/` | 独立整数参考、UART客户端、MF200采集、GUI和电脑端几何模块；另保留未板验的PYNQ部署软件 |
| `scripts/` | 仿真、实现、固件构建/加载、数据与host检查、报告/打包入口 |
| `output/image_system_256x192/`、`output/uart_firmware/` | 匹配硬件、固件、HWH和构建/加载清单 |
| `output/uart_resolution/`、`output/part_measurement/`、`output/uart_live/` | 指定批处理、GUI摘要及选定实际数组；代码包不含所有逐帧归档 |
| `report/`、`docs/` | AMD七节设计报告、接口/要求/复现与证据说明；官方模板PDF/DOCX单独交付 |
| `skill/`、`llm_logs/` | 可复用验证经验、匿名可见消息快照和日期工程摘要 |

代码包`manifest.json`绑定文件SHA和来源变换，`evidence/selection.json`声明代表样本与范围；包内证据清单优先于开发机完整归档。日期摘要不是逐字消息，保留的297条匿名可见消息仍为既有快照（96用户、201助手），不声称平台完整原始导出，也不新增公开工具/系统/开发者内容或内部推理。

历史128×96与115200/2Mbps对照仍保留。固定同输入下事务中位数4.2839638s/0.30025745s、比值14.2676属于UART配置与ARM固件联合变化，非PL/CPU加速比。128旧PL资源6.5 BRAM Tile、约3.2fps验证循环均不作为当前256指标。当前新配置的完整资源为18.5 BRAM Tile，清晰度和负载都增加。

## 交付范围与许可

v6源码、匿名报告内容和选定证据以本次统一文件树为准；远端状态另由发布提交和独立下载回执确认。历史v5发布说明（该历史或独立交付文件未收入本选集）与提交`665c503684f5f92df053103856390f2cf1ffc319`不改写为新功能证据。本次更新不等于已向比赛系统上传。仍待完整系统正面/约45°照片、匿名H.264实物演示视频、亲签授权书、双语海报最终版本及系统回执。

SD启动、Linux/PYNQ/Jupyter、板端独立USB摄像头、HDMI、30fps、CPU/PL独立性能及功耗尚未验收。原PYNQ部署包是另一条待验路径，当前裸机PC辅助成功不能替代其板级验证。

原创部分采用[MIT](LICENSE)；复用PYNQ预设保留BSD 3-Clause，AMD/Xilinx工具、IP及生成组件遵循各自条款，见[第三方声明](THIRD_PARTY_NOTICES.md)。
