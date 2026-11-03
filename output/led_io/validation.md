# LED IO 构建与上板记录

日期：2026-10-29。

## 已完成

- 工具：本机Vivado 2020.2，器件xc7z020clg400-1。
- 综合、布局、布线、bitstream生成全部成功，进程退出码0。
- 最终4条可布线网络全部完成，布线错误0。
- 实现后IO报告核对全部8个引脚及LVCMOS33电平，与源码约束一致。
- DRC设计警告1项：ZPS7-1（没有PS7单元）；无DRC错误。警告保留，没有降低或关闭规则。
- 此设计只有外部输入到LED的组合逻辑，无PS/FCLK/DDR/MIO依赖。没有同步时序频率验收，也不声称通过125MHz时序。
- bitstream：led_io.bit，4,045,666字节。
- SHA256：D1D9B43F654AB046B06D2AF79071127DB4EC739EE1AAFA6390DEAC0E6E9EF66B。
- 下载前核对临时目录bitstream与最终输出SHA256一致。
- JTAG只发现一个目标，匹配唯一xc7z020_1。program_hw_devices成功，工具读取DONE_STATUS=1，进程退出码0。
- 只临时配置PL，没有写TF卡、QSPI Flash或eFUSE。断电后需重新下载。

## 实体观察已通过

| 输入 | 预期输出 | 实测状态 |
| --- | --- | --- |
| SW0 | LD0随开关变化 | 用户确认对应LD0 |
| SW1 | LD1随开关变化 | 用户确认对应LD1 |
| BTN0 | 按住时LD2亮，松开灭 | 用户确认对应LD2 |
| BTN1 | 按住时LD3亮，松开灭 | 用户确认对应LD3 |

用户在2026-10-29回复“动sw1时ld1动 sw0对ld0 btn0对ld2 btn1对ld3”。四路映射实体验证通过。

DONE=1说明PL配置已加载，不能代替上述四路实体观察；当前DONE来自LED实验，不代表PYNQ/Linux启动或SD卡已修复。

## 复现与限制

- 按README运行scripts/build_led_io.ps1；源码保存在rtl/与constraints/。
- 首次受沙箱目录权限限制失败，随后在授权的本机权限下使用ASCII临时目录成功构建；未修改系统安全或隐私设置。
- 官方依据：Xilinx XUP Lab1在PYNQ-Z2上进行纯RTL组合LED逻辑及JTAG验证，https://xilinx.github.io/xup_fpga_vivado_flow/lab1.html 。
- 不使用PS时钟的Zynq设计可经JTAG配置的供应商说明：https://wiki.trenz-electronic.de/display/PD/ZYNQ%2BDesign%2Bnot%2Busing%2BA9%2BCores 。

日志：vivado.log、program_led_io.log；报告：io.rpt、drc.rpt、route_status.rpt、utilization.rpt。
