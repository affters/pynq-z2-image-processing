# UART传输配置与固件版本优化对照（2026-11-01）

相同两幅128×96 RGB固定输入、相同五模式和同一50MHz PL实现下，10个case的UART往返中位数由 **4.283963800秒** 降为 **0.300257450秒**，旧/新中位数之比为 **14.268**，下降 **92.991%**。这是115200与2Mbps配置所对应两版固件的联合对照；不能称为PL核加速比，也不能把全部差额严格归因于串口单因素。

本次仅离线读取现有证据，未访问串口、JTAG、相机或GUI，未修改原始结果。完整逐case数据、文件SHA256及校验结论见[机器可读对照](../output/uart_transport_comparison_20261101.json)。

## 比较范围与正确性

旧组为[2026-10-31固定图结果](../output/uart_firmware/build_20261031_022051_utc_8f9d3191/resume_all_20261031_080130_utc/result.json)，新组为[2026-11-01 2Mbps固定图结果](../output/uart_firmware/build_20261101_015010_utc_b719be66/all_modes_2m/result.json)。每组两个不同固定输入各运行gray、gaussian、sobel、sharpen、equalize五模式，共10个case；COM6、事务超时20秒、协议身份`pynq_uart_image_v1`及记录中的计时说明相同，camera/Linux均为false。模式0/4输出128×96，模式1—3输出126×94。

离线逐项核验通过：

- 两组各自`inputs/frame0.npy/.rgb`和`frame1.npy/.rgb`在shape、uint8类型及全部RGB字节上完全相同，并与共同来源`output/hardware/run_20261029_074543_utc/input_frameN.bin`经`0x00RRGGBB`解包所得RGB完全一致。两幅RGB payload的SHA256依次为`fd2c0c0c4645ebdac3bfc2c0c7f708dd9cd6aeaa69b9bda6f8fd9aca37f0946b`和`346a75a1c7b945ea876a2dbb12203b336ad3829f87e7dde31509c70c7e591241`。
- 20份`pixels.npz`均以`allow_pickle=False`读取；实际/期望/差分数组类型、shape、长度正确，actual=expected、difference全0；保存的expected还与本次按已记hash的`image_reference.py`重新计算的结果相等。每个同名case的新旧actual也完全相等，每组120216输出像素、零差异；CRC32由保存的actual重新核对。
- NPZ只保存actual/expected/difference，不包含输入；输入核验依赖上述NPY/RGB及共同fixture。每份`metrics.json`与对应`result.json`中case逐字段一致，frame、mode、输入/输出shape和收发字节数均匹配。

## 相同口径的计时结果

`uart_roundtrip_seconds`包含请求头/body写出、USB/串口及操作系统等待、ARM控制、DDR/DMA/PL工作、响应头/body接收、协议与响应CRC检查。按[当前客户端](../software/uart_image_client.py)191—217行，计时在请求打包与请求CRC之后开始、在响应CRC之后结束；RGB打包、NumPy参考、响应转数组、存图及显示均在外。两份结果保存了相同`timing_note`，但历史host源码未逐run快照，因此不能声称已经逐字证明两次历史客户端完全相同。

下表秒数顺序均为frame0、frame1，每模式仅两个不同输入样本，均值用于描述，不能当重复随机试验或显著性检验。

| 模式 | 115200两样本/s | 旧均值/s | 2Mbps两样本/s | 新均值/s | 旧均值/新均值 |
|---|---:|---:|---:|---:|---:|
| 0 / gray | 4.319126, 4.327335 | 4.323230 | 0.302971, 0.302330 | 0.302650 | 14.285 |
| 1 / gaussian | 4.287933, 4.279369 | 4.283651 | 0.300442, 0.299487 | 0.299965 | 14.281 |
| 2 / sobel | 4.275424, 4.278341 | 4.276883 | 0.300073, 0.299654 | 0.299864 | 14.263 |
| 3 / sharpen | 4.279995, 4.277525 | 4.278760 | 0.299735, 0.299529 | 0.299632 | 14.280 |
| 4 / equalize | 4.321454, 4.325040 | 4.323247 | 0.303900, 0.303623 | 0.303762 | 14.232 |

10个case的旧/新计时总和为42.971542100/3.011744100秒，均值为4.297154210/0.301174410秒，中位数为4.283963800/0.300257450秒。该总和仅累加case事务计时；没有把INFO、生成参考、写证据文件或整批脚本墙钟时间混入。不能将其倒数直接写成完整相机端到端FPS。

| case | 115200往返/s | 2Mbps往返/s | RGB请求body/B | 灰度响应body/B | 新旧输出差异像素 |
|---|---:|---:|---:|---:|---:|
| frame0_mode0 | 4.319125700 | 0.302970500 | 36864 | 12288 | 0 |
| frame0_mode1 | 4.287932600 | 0.300442000 | 36864 | 11844 | 0 |
| frame0_mode2 | 4.275424500 | 0.300072900 | 36864 | 11844 | 0 |
| frame0_mode3 | 4.279995000 | 0.299734800 | 36864 | 11844 | 0 |
| frame0_mode4 | 4.321453900 | 0.303900200 | 36864 | 12288 | 0 |
| frame1_mode0 | 4.327334700 | 0.302329600 | 36864 | 12288 | 0 |
| frame1_mode1 | 4.279369400 | 0.299487500 | 36864 | 11844 | 0 |
| frame1_mode2 | 4.278340600 | 0.299654300 | 36864 | 11844 | 0 |
| frame1_mode3 | 4.277525400 | 0.299529200 | 36864 | 11844 | 0 |
| frame1_mode4 | 4.325040300 | 0.303623100 | 36864 | 12288 | 0 |

## 传输瓶颈与因果边界

串口为8N1，每字节占10个线比特；每次请求/响应头各32字节。模式0/4总线字节数49216，按名义115200/2000000计算的最小线时为4.272222222/0.246080000秒；模式1—3为48772字节，对应4.233680556/0.243860000秒。十case共489496字节，线时模型合计为42.490972222/2.447480000秒，观测合计减去该模型分别为0.480569878/0.564264100秒。名义波特率之比为17.361111，实际事务改善约14.268，保留的计算、USB/OS等待、分包间隔和协议开销会限制事务改善。

共同PS配置中UART参考100MHz，旧初始化CD=124、BDIV=6，实际115207.373272bps（比名义115200高约0.0064%）；新源码明确MR=0x20即正常8N1、参考不除8，CD=2、BDIV=24，实际2Mbps。上述线时表按结果中的名义波特率计算，未将旧分频微小舍入误差伪装成实测时钟。线时模型与观测量级相符，支持UART是主要瓶颈；它不是把全部时间差分解到单个原因的测量。

已找回旧原始main源码[main.before.c](../evidence/provenance/dma_poison_offline_20261031_084427_c9855a6c/main.before.c)，SHA256=`c7a4952d514c276261ba4383b3fe0743020af1b3eb582c8937a281881f387953`，精确匹配旧manifest。当前`firmware/uart_image/main.c`的hash也精确匹配新manifest，故这两份main可做真实源级差异核验：新版本除波特率选择和显式UART初始化，还增加`fw_dma_poisoned`锁存以及DMA复位失败/错误清理保护；旧版本已包含DMA地址回读检查。新旧ELF不同，不能把此对照表述为只改一个串口参数的控制实验。该新增初始化发生于ready之前，本计时不包含启动过程；其他保护仍是版本差异，未单独量化其耗时贡献。

## 同一器件、时钟和PL资源

两次加载preflight的bit SHA256均为`ebe2f73d9fd2d605629cb751a734b0da2db1341e9c1e7d21a415979a0a65f3eb`，PS初始化脚本SHA256均为`05ff63c18d43e9d8b6b117ab9e5463d76b8235266daec17327d23e09fecc788b`；本次重算当前文件均匹配。`input_manifest.json`记录目标`xc7z020clg400-1`、PL 50MHz，HWH确认核心/DMA时钟50MHz及UART参考100MHz，两次加载日志均枚举到`xc7z020`。这是共同配置和加载记录的证据，没有两次现场时钟寄存器独立测量，也没有物理板唯一序列号，不能增加这样的证明。

单份已布线实现的资源为LUT3625、FF4014、BRAM6.5 tile、DSP0，WNS3.682ns、WHS0.041ns，来源为[utilization.rpt](../output/image_system/utilization.rpt)和[timing_summary.rpt](../output/image_system/timing_summary.rpt)。两个run沿用同一bit，所以PL资源没有因本次UART/固件配置优化发生变化；这是一份实现的沿用，不是两次独立综合/布线测得的资源减少。`last_build`中的对应bit及两份报告与当前副本分别同hash。

## 产物与加载来源

| 固件 | ELF SHA256 |
|---|---|
| old | `0807e023ddb132a7b409aac602b1fcf22d9e09110996b3fc8b6b4f91d22d350c` |
| new | `f60d7dbdb7d0983e76acd46ed0aa59d28410240864cf7678bd51dda9fa788328` |

旧[manifest](../output/uart_firmware/build_20261031_022051_utc_8f9d3191/manifest.json)与新[manifest](../output/uart_firmware/build_20261101_015010_utc_b719be66/manifest.json)的ELF hash均由现存ELF重算核验；两版`start.S`/`link.ld`的manifest hash相同，且匹配当前源文件。manifest内`hardware_test=false`只描述构建阶段，实际10case验收来自独立run结果。

旧加载链为[preflight](../output/uart_firmware/build_20261031_022051_utc_8f9d3191/hardware_20261031_075258_utc_4a5f83ce/preflight.json)与[load.log](../output/uart_firmware/build_20261031_022051_utc_8f9d3191/hardware_20261031_075258_utc_4a5f83ce/load.log)，记录PL配置、PS初始化、入口0x00100000和启动。新[preflight](../output/uart_firmware/build_20261101_015010_utc_b719be66/hardware_20261101_015458_utc_b9cf8951/preflight.json)记录相同bit/PS脚本及新ELF；其[初次load.log](../output/uart_firmware/build_20261101_015010_utc_b719be66/hardware_20261101_015458_utc_b9cf8951/load.log)在PL/PS成功后因ELF路径错误中断，不可称为整次加载成功。[续下载日志](../evidence/provenance/uart_resume/finish_download_20261101.log)及[对应TCL](../evidence/provenance/uart_resume/finish_download_20261101.tcl)记录随后仅下载ELF、入口0x00100000并继续运行，没有重新配置PL/PS。原失败日志保留。

两份run结果未内嵌ELF、bit或host源码hash，其构建归属由目录、相邻preflight/load与恢复记录相互印证，并非run本身的密码学绑定。历史host/loader的逐版本完整快照仍未由两次run分别绑定，不能声称完整历史实验环境已逐字重建。现有ELF、两版源码快照、固定输入、JSON、NPZ及本次所用当前工具源码的路径和hash均记录在新对照JSON中；原JSON报告未改写。

## 二进制一致的离线复现补证

旧`main.c/start.S/link.ld`已归档至[115200基线目录](../firmware/baselines/uart_115200/main.c)，新三源码归档至[2Mbps构建source_snapshot](../output/uart_firmware/build_20261101_015010_utc_b719be66/source_snapshot/main.c)，六份文件均逐一匹配各自原manifest。用支持`-SourceDirectory`与`-VivadoBin`的[构建脚本](../scripts/build_uart_firmware.ps1)和Clang/LLD 7.0.1离线重编：

- [115200重编ELF](../output/uart_firmware/build_20261101_023538_utc_4ca9faa3/uart_image.elf)与原通过ELF逐字节一致，SHA256仍为`0807e023ddb132a7b409aac602b1fcf22d9e09110996b3fc8b6b4f91d22d350c`；[重编manifest](../output/uart_firmware/build_20261101_023538_utc_4ca9faa3/manifest.json)的三源码hash也与原manifest一致。
- [2Mbps重编ELF](../output/uart_firmware/build_20261101_023609_utc_cc2df9f4/uart_image.elf)与原通过ELF逐字节一致，SHA256仍为`f60d7dbdb7d0983e76acd46ed0aa59d28410240864cf7678bd51dda9fa788328`；[重编manifest](../output/uart_firmware/build_20261101_023609_utc_cc2df9f4/manifest.json)的三源码hash也与原manifest一致。

从项目根目录复现编译可使用：

```powershell
& ./scripts/build_uart_firmware.ps1 -BaudRate 115200 -SourceDirectory './firmware/baselines/uart_115200'
& ./scripts/build_uart_firmware.ps1 -BaudRate 2000000 -SourceDirectory './output/uart_firmware/build_20261101_015010_utc_b719be66/source_snapshot'
```

Vivado默认位置为`E:/sailingsi/Vivado/2020.2/bin`，其他安装位置通过`-VivadoBin`指定。这两次只是离线编译，未重新部署，不增加硬件帧数或生成新性能样本。已证明两版固件从归档源码可重建原始二进制；历史host、loader及运行现场的完整复现边界仍单独保留。

比赛优化章节可采用的表述为：“在相同固定输入、模式及50MHz PL实现下，将UART传输配置从115200提升到2Mbps，并采用匹配的新裸机固件，10case事务往返中位数从4.284秒降至0.300秒，下降92.99%，旧/新约14.27；全部120216输出像素保持exact，PL资源沿用同一实现。该数据属于传输与固件版本优化，不代表PL核加速比。”
