# 有界运行与匿名界面取证

`software/uart_live_demo.py`保持原有显式Start、模式切换、逐帧核验和Stop流程。界面结果位置现在显示项目内相对路径；输出目录位于项目外时，只显示会话目录名。实际保存位置、逐帧数组和JSON证据不因显示方式而改变。旧截图原件仍保留，不通过改写图片冒充新截图。

可选参数`--max-frames N`在完成N帧逐像素核验后正常结束当前会话、释放相机与串口并保存`result.json`。`N=0`为原有连续模式，也是默认值。负数在命令行解析阶段拒绝。用户点击Stop可以提前结束；不一致、异常或释放失败仍沿用既有错误与重开门控。

```powershell
& ./.venv-uart/Scripts/python.exe ./software/uart_live_demo.py --port COM6 --baud 2000000 --camera-name 'MF200 Camera' --mode 4 --max-frames 10
```

上述命令仅打开窗口，仍须点击Start；端口需以当次枚举为准。新会话JSON记录`max_frames`与`frame_limit_reached`，不会改写历史JSON。自动结束后保留最后画面，可保存真实界面截图，并检查图像内容、窗口标题等是否仍有其他身份信息。单模式10帧只能证明该次单模式运行，不能改写为五模式验收。

无设备host回归入口为`python scripts/check_uart_live_limits.py`：不创建Tk窗口，使用相机和UART替身驱动真实worker、结果保存与poll清理门控，检查帧数上限、早Stop、默认连续模式、像素不一致、释放失败后禁用重开、路径显示与参数范围。该检查不能替代实际相机及板卡运行。
