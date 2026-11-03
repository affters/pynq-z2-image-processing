---
name: fpga-image-verification
description: Verify gray8 FPGA image cores against explicit integer references, including frame counts, valid-ready stalls, boundary rules, and synthesis evidence. Use for RTL image-core validation and evidence review; this does not certify camera, DMA, display, or board performance.
---

# FPGA图像核验证

将“算法正确”“仿真正确”“综合估计”“上板运行”分别取证。方法可用于其他灰度图像核；本项目只验证了下列核心与尺寸，不宣称跨板复用或通用PYNQ驱动已经验证。

## 先固定数值与接口契约

- 写明颜色顺序、位宽、整数系数、舍入、饱和、输入输出尺寸和边界策略。参考使用更宽整数独立计算，避免照搬RTL位宽错误。
- 只在`valid && ready`边沿计数。堵塞时有效输出与数据保持；输入源同样不能撤销尚未接受的数据。复位丢弃的工作与主结果分开。
- 窗口内区尺寸为`(W-2)×(H-2)`时，不把显示补边算进RTL输出。帧首只有在输入握手时生效，模式帧内保持。
- 整帧核明确start接受条件、busy、固定接收数及done时机。CDF-min均衡需单独验证均匀帧`d=0`与每帧清表；最后输出被反压时不得提前done。

当前数值契约：灰度`(77R+150G+29B+128)>>8`；Gaussian权重和为16，加8再除16；Sobel用L1梯度除4饱和；锐化5中心减四邻饱和。均衡`d=N-cdf_min`，非均匀帧为`floor(((cdf-cdf_min)*255+floor(d/2))/d)`并饱和，CDF未超过最小累计值映射0；均匀帧保持原灰度。换算法时同步重审参考，不复用旧通过结论。

## 使用现有复现流程

从仓库根目录运行，先确认脚本参数中的Vivado／Python路径。Python用于生成参考及比对，不承担被宣称为PL实现的算法。当前工具为Vivado 2020.2；Python需Pillow。路径可通过脚本`-VivadoBin`、`-PythonPath`覆盖；综合脚本使用`-VivadoPath`。

```powershell
& .\scripts\simulate_rgb_to_gray.ps1
& .\scripts\simulate_image_core.ps1 -Kind window -Mode 1 -Width 128 -Height 96
& .\scripts\simulate_image_core.ps1 -Kind window -Mode 2 -Width 128 -Height 96
& .\scripts\simulate_image_core.ps1 -Kind window -Mode 3 -Width 128 -Height 96
& .\scripts\simulate_image_core.ps1 -Kind window -Mode 0 -Width 3 -Height 3
& .\scripts\simulate_image_core.ps1 -Kind equalize -Mode 1 -Width 128 -Height 96
```

脚本prepare输入→xvlog编译→xelab展开→xsim执行→核对通过标记→Python重新计算和逐像素核对。不能只搜索`SIM_PASS`就宣称端到端测试通过；还需工具退出码、输出数量、逐点结果与JSON共同通过。

窗口／均衡测试从仿真cwd读取`count.txt`、`width.txt`、`height.txt`和`input_gray.hex`、`expected_gray.hex`；窗口另有`mode.txt`。均衡TB兼容`W.txt/H.txt`。宽高必须与展开参数一致。当前`filter_reference.py`固定生成三帧，宽高至少3、三帧总输入不超过65,536；不要把RTL更宽的参数范围当成生成器已覆盖。

源文件与向量会复制到ASCII临时路径，再从该cwd仿真，以规避旧版Vivado的路径问题。日志和结果复制回`output/gray/`或`output/filters/<case>/`；源码改动后重跑受影响case，不能沿用旧JSON。

## 必要的行为核对

1. 用定向值、坡度／边界组合、固定种子数据及多帧不同分布比较数值；至少含均匀帧，避免旧统计或窗口残留被同一图像掩盖。
2. 插入输入气泡、长输出反压和最后像素反压，检查数值稳定、顺序、不重不漏及总数。检查复位后的遗留状态；对帧核检查idle拒收与busy时start忽略。
3. 用最小有效窗口核对尺寸：本项目3×3输入每帧只输出1点，三帧应为3点。展示补边与算法输出分开记录。
4. 将主向量输出与定向预检输出分开：主结果文件只能含metadata描述的数据，不能把复位前或额外常量帧混入统计。
5. 失败时保留工具日志和首个不匹配的索引／期望／实际。先分辨计数、顺序、算法、边界、握手还是参数问题；不得通过改期望值掩盖RTL错误。

## 资源和时序的解释

如需本项目独立综合估计，可运行：

```powershell
& .\scripts\synthesize_image_cores.ps1
```

此入口只串行OOC综合三个核，不布局布线、不产生用于宣称系统完成的下载结果。读取`utilization.rpt`和`timing_estimate.rpt`原始数据，记录器件、参数、时钟及外部I/O假设。10 ns是目标；负WNS表示该估计约束未满足，正WNS也不证明整机实现闭合。不要从仿真时钟换算实机FPS，或把多个独立核报告直接相加当作最终系统占用。

## 已验证效果与来源

- `output/gray/verification.json`：14,560点选定整数灰度exact，hardware_test=false。
- `output/filters/window_m1_128x96/`、`window_m2_128x96/`、`window_m3_128x96/`：各三帧36,864输入、35,532输出exact；`window_m0_3x3/`三帧输出3点exact。
- `output/filters/equalize_m1_128x96/`：三帧36,864输出exact，包含均匀帧保持；定向TB检查start、done及反压。
- `output/synthesis/`：RGB、邻域、均衡独立估计WNS分别+1.900、-2.810、-2.130 ns。该观察促使将“综合成功”和“时序满足／上板成功”分开。
- `output/led_io/validation.md`：LED上板与用户观察仅支持纯PL实验；该观察促使将JTAG DONE和PS／卡启动分开。
- `scripts/filter_reference.py`与各TB：明确内区、数值舍入、三帧与复位场景，是本技能的具体方法来源。

本技能总结的是实际观察和验证边界，不伪造一份失败历史。Gaussian合成帧MSE变化及均衡标准差变化只描述指定样本，不是通用视觉质量指标。

## 失效条件与停止边界

- 输入颜色顺序、算法、尺寸、边界、模式或握手改变时，旧参考和旧case不能直接复用为通过证据；先更新契约再验证。
- AXI/DMA、相机、显示、DDR、CDC、真实频率或功耗需要各自的集成与板级验证；本技能不会把功能仿真提升为这些结论。
- 工具路径／依赖缺失、参数不符、计数／像素不匹配、超时或未解决时序约束时，报告失败及证据，不继续填写成功结论。
- 当前脚本的向量上限或机器资源不支持目标尺寸时，先调整生成器／测试方案并重新验证，不静默截断。
- 本流程不授权下载硬件、重写存储卡、发布仓库或改变用户软件设置；另行执行这些动作时遵循实际任务授权。
