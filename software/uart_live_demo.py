"""Tk camera/FPGA UART demo. Launch explicitly; importing opens no devices.

The worker owns the selected MF200 camera and UART. Tk widgets are updated only
on the main thread. Stop waits for the current finite UART transaction and for
independent cleanup; restart stays disabled if cleanup fails.
"""
import argparse
import datetime
import json
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

from image_reference import MODES, process_reference
from uart_camera_demo import (create_result_directory, open_selected_camera,
                              read_camera_rgb, save_verified_case)
from uart_image_client import BAUDRATES, FrameClient

MODE_TEXT = {0: "灰度", 1: "Gaussian 去噪", 2: "Sobel 边缘", 3: "锐化", 4: "直方图均衡"}
ROOT = Path(__file__).resolve().parents[1]


def evidence_display_path(directory):
    """Show a useful evidence location without a personal absolute path."""
    directory = Path(directory).resolve()
    try:
        return directory.relative_to(ROOT).as_posix()
    except ValueError:
        return directory.name


def nonnegative_frames(value):
    count = int(value)
    if count < 0:
        raise argparse.ArgumentTypeError("max-frames must be nonnegative")
    return count


class LiveDemo:
    def __init__(self, root, args):
        self.root = root
        self.args = args
        self._thread = None
        self._stop = threading.Event()
        self._events = queue.Queue()
        self._frames = queue.Queue(maxsize=1)
        self._mode_lock = threading.Lock()
        self._mode = args.mode
        self._close_requested = False
        self._terminal = None
        self._cleanup_failed = False
        self._photos = []
        root.title("PYNQ-Z2 五模式图像处理 — USB串口演示")
        root.geometry("1110x700")
        root.minsize(1060, 650)
        root.protocol("WM_DELETE_WINDOW", self.close_window)
        style = ttk.Style(root)
        style.configure("TLabel", font=("Microsoft YaHei UI", 10))
        style.configure("TButton", font=("Microsoft YaHei UI", 10))
        controls = ttk.Frame(root, padding=10)
        controls.pack(fill="x")
        ttk.Label(controls, text="串口").grid(row=0, column=0, padx=3)
        self.port_var = tk.StringVar(value=args.port)
        self.port_entry = ttk.Entry(controls, textvariable=self.port_var, width=10)
        self.port_entry.grid(row=0, column=1, padx=3)
        ttk.Label(controls, text="波特率").grid(row=0, column=2, padx=3)
        self.baud_var = tk.StringVar(value=str(args.baud))
        self.baud_box = ttk.Combobox(controls, textvariable=self.baud_var,
                                     values=[str(value) for value in BAUDRATES], width=11, state="readonly")
        self.baud_box.grid(row=0, column=3, padx=3)
        ttk.Label(controls, text="模式").grid(row=0, column=4, padx=3)
        self.mode_box = ttk.Combobox(controls, values=["%d %s" % (key, MODE_TEXT[key]) for key in MODES],
                                     width=21, state="readonly")
        self.mode_box.current(args.mode)
        self.mode_box.bind("<<ComboboxSelected>>", self.mode_changed)
        self.mode_box.grid(row=0, column=5, padx=3)
        self.start_button = ttk.Button(controls, text="Start 开始", command=self.start)
        self.start_button.grid(row=0, column=6, padx=8)
        self.stop_button = ttk.Button(controls, text="Stop 停止", command=self.stop, state="disabled")
        self.stop_button.grid(row=0, column=7, padx=3)
        self.status = tk.StringVar(value="已停止。点击 Start 后才打开 MF200 摄像头和指定串口。")
        ttk.Label(root, textvariable=self.status, padding=(12, 3)).pack(fill="x")
        self.camera_info = tk.StringVar(value="摄像头限定：MF200 Camera，VID 0C45 / PID 6366；不使用电脑内置摄像头。")
        ttk.Label(root, textvariable=self.camera_info, padding=(12, 3)).pack(fill="x")
        images = ttk.Frame(root, padding=10)
        images.pack(fill="both", expand=True)
        images.columnconfigure(0, weight=1)
        images.columnconfigure(1, weight=1)
        images.rowconfigure(0, weight=1)
        self.input_panel = ttk.LabelFrame(images, text="摄像头 RGB 输入（送入 FPGA 的 128×96 图像）", padding=5)
        self.input_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.output_panel = ttk.LabelFrame(images, text="FPGA 输出", padding=5)
        self.output_panel.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        self.input_label = tk.Label(self.input_panel, background="#20252b", foreground="white", text="等待已验证图像")
        self.output_label = tk.Label(self.output_panel, background="#20252b", foreground="white", text="等待已验证图像")
        self.input_label.pack(fill="both", expand=True)
        self.output_label.pack(fill="both", expand=True)
        self.metrics = tk.StringVar(value="每一帧均与独立整数参考逐像素比较；不一致时停止。")
        ttk.Label(root, textvariable=self.metrics, padding=(12, 5)).pack(fill="x")
        self.evidence = tk.StringVar(value="串口往返时间包括传输和板端处理，不代表 FPGA 核延迟。显示图像放大 4 倍。")
        ttk.Label(root, textvariable=self.evidence, padding=(12, 8), wraplength=1070).pack(fill="x")
        root.after(50, self.poll)

    def mode_changed(self, _event=None):
        with self._mode_lock:
            self._mode = int(self.mode_box.get().split(" ", 1)[0])

    def _set_controls(self, running):
        self.start_button.configure(state="disabled" if running or self._cleanup_failed else "normal")
        self.stop_button.configure(state="normal" if running and not self._stop.is_set() else "disabled")
        self.port_entry.configure(state="disabled" if running else "normal")
        self.baud_box.configure(state="disabled" if running else "readonly")

    def start(self):
        if self._cleanup_failed or (self._thread is not None and self._thread.is_alive()):
            return
        port = self.port_var.get().strip()
        try:
            baud = int(self.baud_var.get())
            if not port or baud not in BAUDRATES:
                raise ValueError("请选择明确串口和已支持的波特率")
        except ValueError as exc:
            self.status.set(str(exc))
            return
        self._stop = threading.Event()
        self._terminal = None
        while not self._frames.empty():
            try:
                self._frames.get_nowait()
            except queue.Empty:
                break
        self.status.set("正在连接并验证固件、选择 MF200 摄像头…")
        self._set_controls(True)
        self._thread = threading.Thread(target=self.worker, args=(port, baud, self._stop), daemon=True)
        self._thread.start()

    def stop(self):
        if self._thread is not None and self._thread.is_alive():
            self._stop.set()
            self.status.set("Stopping：等待当前有界传输结束并释放摄像头与串口…")
            self.stop_button.configure(state="disabled")

    def close_window(self):
        self._close_requested = True
        if self._thread is not None and self._thread.is_alive():
            self.stop()
        else:
            self.root.destroy()

    def _latest_frame(self, frame):
        try:
            self._frames.put_nowait(frame)
        except queue.Full:
            try:
                self._frames.get_nowait()
            except queue.Empty:
                pass
            try:
                self._frames.put_nowait(frame)
            except queue.Full:
                pass

    def worker(self, port, baud, stop_event):
        capture = client = directory = None
        max_frames = getattr(self.args, "max_frames", 0)
        result = dict(started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      port=port, baudrate=baud, source="live_mf200_camera", camera_capture_test=False,
                      hardware_test=False, camera_test=False, linux_test=False, sd_used=False,
                      cases=[], cleanup_errors=[], error=None, verified_modes=[], all_modes_verified=False,
                      max_frames=max_frames, frame_limit_reached=False,
                      timing_note="UART roundtrip includes transfer and board processing. Verified display throughput includes capture, CPU reference, UART and saving; it is not PL latency.")
        try:
            directory = create_result_directory(self.args.output_root / ("session_" +
                datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S_") +
                __import__("uuid").uuid4().hex[:8]))
            client = FrameClient(port, baudrate=baud, timeout=self.args.timeout)
            client.open()
            result["firmware_info"] = client.firmware_info
            if stop_event.is_set():
                return
            capture, camera_metadata = open_selected_camera(self.args.camera_name)
            result["camera"] = camera_metadata
            result["camera_capture_test"] = True
            self._events.put(("camera", camera_metadata))
            run_started = time.perf_counter()
            index = 0
            while not stop_event.is_set():
                with self._mode_lock:
                    mode = self._mode
                rgb, source_shape = read_camera_rgb(capture)
                if stop_event.is_set():
                    break
                expected = process_reference(rgb, mode)
                actual, details = client.process(rgb, mode)
                metrics = save_verified_case(directory / ("frame%06d_mode%d" % (index, mode)),
                                             rgb, actual, expected, details, index, mode, source_shape)
                result["cases"].append(metrics)
                if not metrics["exact_match"]:
                    raise AssertionError("摄像头实际输入与 FPGA 输出逐像素比较不一致")
                result["hardware_test"] = True
                index += 1
                elapsed = time.perf_counter() - run_started
                metrics["verified_loop_frames_per_second"] = index / elapsed
                self._latest_frame((rgb, actual, metrics, str(directory)))
                if max_frames and index >= max_frames:
                    result["frame_limit_reached"] = True
                    break
        except Exception as exc:
            result["error"] = "%s: %s" % (type(exc).__name__, exc)
        finally:
            for name, resource, method in (("camera", capture, "release"), ("uart", client, "close")):
                if resource is not None:
                    try:
                        getattr(resource, method)()
                    except Exception as exc:
                        result["cleanup_errors"].append("%s: %s" % (name, exc))
            result["verified_modes"] = sorted({item["mode"] for item in result["cases"] if item["exact_match"]})
            result["camera_test"] = bool(result["camera_capture_test"] and result["hardware_test"]
                                         and not result["error"] and not result["cleanup_errors"])
            result["all_modes_verified"] = bool(result["camera_test"] and result["verified_modes"] == list(MODES))
            result["completed_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            if directory is not None:
                try:
                    (directory / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
                except Exception as exc:
                    result["error"] = "结果写入失败: %s" % exc
                    result["camera_test"] = False
                    result["all_modes_verified"] = False
            self._events.put(("finished", (result, str(directory) if directory else None)))

    def render_frame(self, event):
        rgb, actual, metrics, directory = event
        input_image = ImageTk.PhotoImage(Image.fromarray(rgb).resize((rgb.shape[1] * 4, rgb.shape[0] * 4), Image.Resampling.NEAREST))
        output_image = ImageTk.PhotoImage(Image.fromarray(actual).resize((actual.shape[1] * 4, actual.shape[0] * 4), Image.Resampling.NEAREST))
        self._photos = [input_image, output_image]
        self.input_label.configure(image=input_image, text="")
        self.output_label.configure(image=output_image, text="")
        mode = metrics["mode"]  # Actual completed frame, independent of the current selector.
        source = metrics["source_bgr_shape"]
        self.input_panel.configure(text="摄像头采集 %d×%d → RGB 输入 128×96（放大4倍）" % (source[1], source[0]))
        self.output_panel.configure(text="FPGA %s，实际输出 %d×%d（放大4倍）" %
                                    (MODE_TEXT[mode], actual.shape[1], actual.shape[0]))
        self.metrics.set("帧 %d | 实际模式 %d %s | 像素一致 | UART往返 %.3fs | 已验证处理吞吐 %.2f 帧/秒" %
                         (metrics["frame"], mode, MODE_TEXT[mode], metrics["uart_roundtrip_seconds"],
                          metrics["verified_loop_frames_per_second"]))
        self.evidence.set("实际图像与逐帧结果：" + evidence_display_path(directory))

    def poll(self):
        try:
            while True:
                kind, value = self._events.get_nowait()
                if kind == "camera":
                    selected = value["selected"]
                    self.camera_info.set("已连接 %s，DirectShow index %d，VID %s / PID %s。" %
                                         (selected["name"], selected["index"], selected["vid"], selected["pid"]))
                    if not self._stop.is_set():
                        self.status.set("运行中：仅显示 FPGA 与独立参考逐像素一致的帧。")
                elif kind == "finished":
                    self._terminal = value
        except queue.Empty:
            pass
        try:
            self.render_frame(self._frames.get_nowait())
        except queue.Empty:
            pass
        if self._terminal is not None and (self._thread is None or not self._thread.is_alive()):
            result, directory = self._terminal
            self._terminal = None
            self._cleanup_failed = bool(result["cleanup_errors"])
            if self._cleanup_failed:
                self.status.set("释放设备失败，已锁定再次开始：" + "; ".join(result["cleanup_errors"]))
            elif result["error"]:
                self.status.set("已停止并释放设备；错误：" + result["error"])
            else:
                self.status.set("已停止，摄像头与串口已释放；已验证 %d 帧，模式 %s。" %
                                (len(result["cases"]), result["verified_modes"]))
            self._set_controls(False)
            if directory:
                self.evidence.set("本次实际运行记录：" + evidence_display_path(directory))
        if self._close_requested and (self._thread is None or not self._thread.is_alive()):
            self.root.destroy()
            return
        self.root.after(50, self.poll)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, choices=BAUDRATES, default=115200)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--camera-name", default="MF200 Camera")
    parser.add_argument("--mode", type=int, choices=list(MODES), default=0)
    parser.add_argument("--max-frames", type=nonnegative_frames, default=0,
                        help="Stop and release devices after N verified frames (0: continuous)")
    parser.add_argument("--output-root", type=Path, default=Path(__file__).resolve().parents[1] / "output" / "uart_live")
    args = parser.parse_args()
    root = tk.Tk()
    LiveDemo(root, args)
    root.mainloop()


if __name__ == "__main__":
    main()
