This is an anonymized selected package copy. Body SHA identifiers describe original evidence; actual packaged bytes and source identifiers are recorded separately in manifest.json. Unselected private links are explicitly removed.

# 2026-11-02恢复与测试检查点

本页记录本轮已发生的板卡恢复、固定图、真实相机和GUI测试。本文编写仅读取已保存证据，不操作相机、串口、JTAG或GUI。历史失败和后续成功分别保留；旧PID、窗口和设备序号不能用于推断未来状态。

## 当前归档位置

- 本轮使用COM6及MF200 Camera，DirectShow枚举index为0、VID为0C45、PID为6366；HD Webcam本轮为index1。下次仍需重新枚举，不把历史index1或本轮index0写成固定设备编号。
- 已恢复匹配的2Mbps裸机ARM/FPGA程序。固定图与真实MF200各两帧×五模式，分别10 cases、120216输出像素全部exact。
- 第一轮GUI已正常Stop并保存[会话结果](../output/uart_live/session_20261102_101032_950a05f0/result.json)：9291帧全部exact，mode0灰度884帧、mode1 Gaussian8407帧，verified_modes=[0,1]、all_modes_verified=false。它不是本轮GUI五模式覆盖的证据。
- 同GUI重新Start后的[第二会话](../output/uart_live/session_20261102_111935_29c421e6/result.json)也已正常Stop并释放相机和串口：750帧全部exact，mode2 Sobel392帧、mode3锐化211帧、mode4当前帧均衡147帧，verified_modes=[2,3,4]、all_modes_verified=false。两会话合计10041帧，合计覆盖五模式；没有单个会话覆盖五模式。归档时GUI保留最后mode4图像，后续仍须重新检查当前窗口和设备状态。

## 初态、失败与恢复

1. 首次[INFO结果](../output/uart_demo/run_20261102_090956_utc_6d80ef15/result.json)在2000000 baud、5秒期限内超时；info_handshake_passed=false、hardware_test=false、error为`TimeoutError: UART transaction deadline expired`。这不是本轮最终状态。
2. 随后[只读JTAG日志](../evidence/provenance/uart_resume/probe_20261102_091059_utc/read_only.log)显示APU及双核可见、PL为`FPGA is not configured`，UART MIO14/15均为`0x00001601`默认值。boot读回为F8000258=`0040200A`、F800025C=`00000005`。初次INFO失败与该加载前状态相符；不能据此推断卡损坏、精确断电时长或恢复后的程序状态。
3. [本轮加载日志](../output/uart_firmware/build_20261101_015010_utc_b719be66/hardware_20261102_092223_utc_6360d3eb/load.log)先确认PL未配置，再配置匹配bit、执行PS初始化、下载ELF，入口PC=`0x00100000`，最终出现`UART_IMAGE_FIRMWARE_STARTED`。[preflight](../output/uart_firmware/build_20261101_015010_utc_b719be66/hardware_20261102_092223_utc_6360d3eb/preflight.json)记录sd_write_performed=false、flash_write_performed=false；[ELF布局检查](../output/uart_firmware/build_20261101_015010_utc_b719be66/hardware_20261102_092223_utc_6360d3eb/elf_layout.json)通过。
4. 加载后[INFO](../output/uart_demo/run_20261102_092320_utc_f9039813/result.json)通过，返回`pynq_uart_image_v1`、info_roundtrip_seconds约0.033812，error=null。INFO仅证明协议握手，不替代图像测试。

本轮沿用11月1日已通过的构建`output/uart_firmware/build_20261101_015010_utc_b719be66/`，未重新综合PL。当前ELF、bit、PS初始化及三份固件源码读取哈希与manifest/preflight逐项一致：

| 对象 | SHA256 |
| --- | --- |
| uart_image.elf | `f60d7dbdb7d0983e76acd46ed0aa59d28410240864cf7678bd51dda9fa788328` |
| image_system.bit | `ebe2f73d9fd2d605629cb751a734b0da2db1341e9c1e7d21a415979a0a65f3eb` |
| ps7_init.tcl | `05ff63c18d43e9d8b6b117ab9e5463d76b8235266daec17327d23e09fecc788b` |
| main.c | `918f68b333cc2412cee22bf083ddc54c3354eaf519ed7ab80cfe18a794fa32fa` |
| start.S | `97ed66a44e8071bb469089d44fc13ab4f4b1ee9f3dabacd6da2177f59b4a2ef5` |
| link.ld | `9ca42b3aacb374917761e30a2c4469d4cc763b79163b477b2ab918e22d615245` |

构建manifest中的hardware_test=false仍只表示编译阶段；本轮硬件通过由独立运行结果证明，不修改原manifest。

## 已保存的本轮测试

| 实验 | 原始结果 | 已证明的范围 |
| --- | --- | --- |
| 固定图 | [run_20261102_092320_utc_3e021f3a](../output/uart_demo/run_20261102_092320_utc_3e021f3a/result.json) | 两帧各五模式，共10 cases/120216像素exact；mismatch_pixels与max_abs_error均0；camera=false、linux=false、error=null。UART往返0.2987654–0.3033597秒/case |
| 真实MF200批量 | [run_20261102_092416_utc_30b93c8f](../output/uart_camera/run_20261102_092416_utc_30b93c8f/result.json) | 两个真实捕获帧各五模式，共10 cases/120216像素exact；camera_capture_test/camera_test/hardware_test=true，linux_test/sd_used=false，error=null、cleanup_errors=[]。UART往返0.2991367–0.3037281秒/case |
| GUI第一会话 | [session_20261102_101032_950a05f0](../output/uart_live/session_20261102_101032_950a05f0/result.json) | 9291帧全部exact；mode0=884、mode1=8407；verified_modes=[0,1]、all_modes_verified=false，camera_capture_test/camera_test/hardware_test=true，linux_test/sd_used=false，error=null、cleanup_errors=[]。最后验证循环吞吐3.2065530841fps |
| 同GUI重新Start后的第二会话 | [session_20261102_111935_29c421e6](../output/uart_live/session_20261102_111935_29c421e6/result.json) | 750帧全部exact；mode2=392、mode3=211、mode4=147；verified_modes=[2,3,4]、all_modes_verified=false，camera_capture_test/camera_test/hardware_test=true，linux_test/sd_used=false，error=null、cleanup_errors=[]。最后验证循环吞吐3.2022919502fps |

两会话的result.json完整字节SHA256如下，原文件未改动；两份原始all_modes_verified=false均保留，五模式覆盖结论仅来自合并后的模式集合：

| 会话 | result.json SHA256 |
| --- | --- |
| session_20261102_101032_950a05f0 | `70f9047a49c15ed5bb2c1b6d8b44d108698cb6f593c1a94f7db10129b0d7b062` |
| session_20261102_111935_29c421e6 | `377435a839d755e8143752cf99a954586327826b1ed6a4cae873b4121540555f` |

相机元数据明确：DirectShow、640×480 BGR，INTER_AREA缩放并转换为128×96 RGB。实际通路是MF200→电脑采集/转换→USB-UART→裸机ARM→DDR→AXI DMA→PL→DMA→DDR→UART→电脑整数参考比较。模式0/4输出128×96，模式1—3输出126×94有效内区。

GUI第一会话UTC为10:10:32.863002–10:58:55.915653，对应北京时间2026-11-02 18:10:32–18:58:55。根任务现场操作记录表明，多次窗口最小化、用户输入保护和桌面连接延迟影响了切换及停止操作，使实际运行较长；这是本轮真实记录，不能改写为事先安排的短测。现场曾看到桌沿和电缆，随后用户调整为纸张；该观察不构成文字识别准确率、文字增强质量或固定纸张场景的量化结论。

第二会话UTC为11:19:35.878181–11:23:34.812182，对应北京时间2026-11-02 19:19:35–19:23:34。本轮根任务现场观察到Sobel、锐化和当前帧均衡的实际输出，随后正常Stop，设备已释放，窗口保留最后mode4图。该停止/重开证明同GUI的正常生命周期，不扩展为全部异常场景验收。

本次编写读取两份JSON并复算case数量、模式计数、输出像素总数和最大误差字段，核对两份result.json哈希；没有重新读取全部10041帧数组，也未重新执行硬件。原始逐帧PNG、NPZ与metrics保留在会话子目录。GUI的3.2066/3.2023fps包含采集、CPU参考、UART及结果保存，UART往返也包含传输和板端处理；两者都不是PL核延迟、实际屏幕刷新率、CPU/PL加速比或30fps实时视频结论。

## 下次恢复

先枚举设备和检查旧程序占用。若当前GUI已停止且程序仍响应，可直接Start，不重新加载已配置PL。若确需冷启动加载，沿用11月1日恢复历史（本包未选入该旧检查点，复现入口在README）的匹配构建、INFO门控和分步测试入口；新一次运行使用新目录。路径映射、PL已配置等加载拒绝不绕过，失败先留新日志。

## 保持未验收的范围

已归档未改动的第二会话停止界面截图（本地未匿名原件，未收入本匿名包），显示750帧、模式[2,3,4]及设备已释放。截图底部有本地账户路径，尚未完成匿名报告用图处理；保留原件，不直接公开。

本轮未修复SD启动，未验收Linux/PYNQ、板端Python/Jupyter、板端USB摄像头采集、HDMI、实测功耗、独立CPU/PL性能或30fps。用户灯未由本图像程序驱动，其不亮不是本次图像测试失败判据。整机正面与约45°真实照片、匿名软件截图、报告/海报/代码包一致性、公开发布及正式上传回执仍需最终交付核对；本轮新增证据不自动更新已冻结的v4材料。
