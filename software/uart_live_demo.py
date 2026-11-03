"""Tk camera/FPGA UART demo. Launch explicitly; importing opens no devices.

The worker owns the selected MF200 camera and UART. Tk widgets are updated only
on the main thread. Stop waits for the current finite UART transaction and for
independent cleanup; restart stays disabled if cleanup fails.
"""
import argparse
import copy
import datetime
import json
import math
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageOps, ImageTk

from image_reference import MODES, process_reference
from uart_camera_demo import (create_result_directory, open_selected_camera,
                              read_camera_rgb, save_verified_case)
from uart_image_client import BAUDRATES, FrameClient, WIDTH, HEIGHT, resolution_profile
from part_measurement import analyze_edges, calibration_scale, render_measurement_overlay

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
        width, height, _ = resolution_profile(getattr(args, "width", WIDTH),
                                               getattr(args, "height", HEIGHT))
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
        self._display_event = None
        self._measurement_lock = threading.Lock()
        self._measurement_settings = dict(enabled=False, threshold=40, min_area=80,
                                         close_gaps=True,
                                         roi=None, mm_per_pixel=None, calibration_points=None,
                                         calibration_known_mm=None, version=0)
        self._measurement_shape = None
        self._calibration_pending = None
        self._roi_drag_start = None
        self._output_geometry = None
        root.title("PYNQ-Z2 五模式图像处理 — USB串口演示" +
                   ("（%d×%d）" % (width, height) if (width, height) != (WIDTH, HEIGHT) else ""))
        root.geometry("1110x780")
        root.minsize(1060, 720)
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
        measure_controls = ttk.Frame(root, padding=(10, 2))
        measure_controls.pack(fill="x")
        self.measure_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(measure_controls, text="轮廓/尺寸测量（电脑端）", variable=self.measure_enabled,
                        command=self.measurement_toggled).grid(row=0, column=0, padx=3)
        ttk.Label(measure_controls, text="阈值").grid(row=0, column=1)
        self.threshold_var = tk.StringVar(value="40")
        threshold_entry = ttk.Entry(measure_controls, textvariable=self.threshold_var, width=4)
        threshold_entry.grid(row=0, column=2, padx=3)
        ttk.Label(measure_controls, text="最小面积px²").grid(row=0, column=3)
        self.min_area_var = tk.StringVar(value="80")
        area_entry = ttk.Entry(measure_controls, textvariable=self.min_area_var, width=5)
        area_entry.grid(row=0, column=4, padx=3)
        ttk.Button(measure_controls, text="应用", command=self.apply_measurement_parameters,
                   width=5).grid(row=0, column=5, padx=3)
        ttk.Label(measure_controls, text="参照长度mm").grid(row=0, column=6)
        self.known_length_var = tk.StringVar(value="20")
        ttk.Entry(measure_controls, textvariable=self.known_length_var, width=6).grid(row=0, column=7, padx=3)
        ttk.Button(measure_controls, text="两点标定", command=self.begin_calibration,
                   width=8).grid(row=0, column=8, padx=3)
        ttk.Button(measure_controls, text="清除标定", command=self.clear_calibration,
                   width=8).grid(row=0, column=9, padx=3)
        ttk.Button(measure_controls, text="全图ROI", command=self.reset_measurement_roi,
                   width=8).grid(row=0, column=10, padx=3)
        self.close_gaps_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(measure_controls, text="连接断边", variable=self.close_gaps_var,
                        command=self.gap_connection_toggled).grid(row=0, column=11, padx=3)
        threshold_entry.bind("<Return>", self.apply_measurement_parameters)
        area_entry.bind("<Return>", self.apply_measurement_parameters)
        self.measurement_info = tk.StringVar(value="启用后使用已验证的FPGA Sobel边缘；右图拖框选ROI，测量框内最大外轮廓的外接长短边。")
        ttk.Label(root, textvariable=self.measurement_info, padding=(12, 2), wraplength=1070).pack(fill="x")
        ttk.Label(root, text="毫米值为估计：相机须垂直、参照与零件须同平面；移动相机、焦距或测量平面后须清除标定并重做。",
                  padding=(12, 1), wraplength=1070).pack(fill="x")
        images = ttk.Frame(root, padding=10)
        images.pack(fill="both", expand=True)
        images.columnconfigure(0, weight=1)
        images.columnconfigure(1, weight=1)
        images.rowconfigure(0, weight=1)
        self.input_panel = ttk.LabelFrame(images, text="摄像头原图预览（FPGA 输入为 %d×%d）" % (width, height), padding=5)
        self.input_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.output_panel = ttk.LabelFrame(images, text="FPGA 输出", padding=5)
        self.output_panel.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        self.show_source = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.input_panel, text="显示相机原图（仅预览）", variable=self.show_source,
                        command=self.refresh_preview).pack(anchor="w")
        self.input_label = tk.Label(self.input_panel, background="#20252b", foreground="white", text="等待已验证图像")
        self.output_label = tk.Label(self.output_panel, background="#20252b", foreground="white", text="等待已验证图像",
                                     borderwidth=0, highlightthickness=0, anchor="center")
        self.output_label.bind("<ButtonPress-1>", self.measurement_pointer_down)
        self.output_label.bind("<ButtonRelease-1>", self.measurement_pointer_up)
        self.input_label.pack(fill="both", expand=True)
        self.output_label.pack(fill="both", expand=True)
        self.metrics = tk.StringVar(value="每一帧均与独立整数参考逐像素比较；不一致时停止。")
        ttk.Label(root, textvariable=self.metrics, padding=(12, 5)).pack(fill="x")
        self.evidence = tk.StringVar(value="左侧原图仅供预览；FPGA 输入%d×%d，右侧为实际硬件输出放大%d倍。串口往返不是核延迟。" %
                                    (width, height, 512 // width))
        ttk.Label(root, textvariable=self.evidence, padding=(12, 8), wraplength=1070).pack(fill="x")
        root.after(50, self.poll)

    def mode_changed(self, _event=None):
        with self._mode_lock:
            self._mode = int(self.mode_box.get().split(" ", 1)[0])
        if self._mode != 2 and self._measurement_snapshot().get("enabled"):
            self.measure_enabled.set(False)
            self._update_measurement_settings(enabled=False)
            self._reset_measurement_geometry("已离开Sobel，尺寸测量已关闭。")
            self.refresh_preview()

    def _measurement_snapshot(self):
        # Host lifecycle checks instantiate __new__ without new optional controls.
        if not hasattr(self, "_measurement_lock"):
            return dict(enabled=False)
        with self._measurement_lock:
            return copy.deepcopy(self._measurement_settings)

    def _update_measurement_settings(self, **changes):
        with self._measurement_lock:
            self._measurement_settings.update(changes)
            self._measurement_settings["version"] += 1

    def _reset_measurement_geometry(self, message=None):
        if not hasattr(self, "_measurement_lock"):
            return
        self._update_measurement_settings(roi=None, mm_per_pixel=None, calibration_points=None,
                                          calibration_known_mm=None)
        self._measurement_shape = None
        self._calibration_pending = None
        self._roi_drag_start = None
        if message:
            self.measurement_info.set(message)

    def apply_measurement_parameters(self, _event=None):
        try:
            threshold = int(self.threshold_var.get())
            min_area = float(self.min_area_var.get())
            if not 1 <= threshold <= 255 or not math.isfinite(min_area) or min_area <= 0:
                raise ValueError()
        except ValueError:
            self.measurement_info.set("参数无效：阈值须为1～255整数，最小面积须为有限正数。")
            return False
        self._update_measurement_settings(threshold=threshold, min_area=min_area)
        self.measurement_info.set("参数已应用，等待下一幅已验证的Sobel边缘图。")
        self.refresh_preview()
        return True

    def measurement_toggled(self):
        enabled = bool(self.measure_enabled.get())
        if enabled and not self.apply_measurement_parameters():
            self.measure_enabled.set(False)
            return
        self._update_measurement_settings(enabled=enabled)
        self._reset_measurement_geometry("测量已启用：未标定时仅显示像素；右图拖框选ROI，再用已知长度进行两点标定。" if enabled
                                         else "尺寸测量已关闭，右侧恢复FPGA原始输出。")
        if enabled:
            self.mode_box.current(2)
            with self._mode_lock:
                self._mode = 2
        self.refresh_preview()

    def reset_measurement_roi(self):
        self._roi_drag_start = None
        self._update_measurement_settings(roi=None)
        self.measurement_info.set("已恢复全图ROI；将选择最大外轮廓，复杂背景建议拖框限定待测物。")
        self.refresh_preview()

    def gap_connection_toggled(self):
        enabled = bool(self.close_gaps_var.get())
        self._update_measurement_settings(close_gaps=enabled)
        self.measurement_info.set("连接断边%s，等待下一帧；邻近文字被连入轮廓时可关闭此项。" %
                                  ("已开启" if enabled else "已关闭"))
        self.refresh_preview()

    def clear_calibration(self):
        self._calibration_pending = None
        self._update_measurement_settings(mm_per_pixel=None, calibration_points=None,
                                          calibration_known_mm=None)
        self.measurement_info.set("标定已清除，尺寸仅显示px；重新标定后才显示毫米估计值。")
        self.refresh_preview()

    def begin_calibration(self):
        event = self._display_event
        if not self._measurement_snapshot().get("enabled") or event is None or event[2]["mode"] != 2:
            self.measurement_info.set("请先启用测量并等待右侧显示已验证的Sobel边缘图。")
            return
        # Beginning a replacement calibration invalidates the former scale,
        # including when the new length or subsequent point selection is bad.
        self._calibration_pending = None
        self._roi_drag_start = None
        self._update_measurement_settings(mm_per_pixel=None, calibration_points=None,
                                          calibration_known_mm=None)
        try:
            known_mm = float(self.known_length_var.get())
            if not math.isfinite(known_mm) or known_mm <= 0:
                raise ValueError()
        except ValueError:
            self.measurement_info.set("参照长度须为有限的正数，单位mm；原标定已清除。")
            self.refresh_preview()
            return
        self._calibration_pending = dict(points=[], known_mm=known_mm)
        self._roi_drag_start = None
        self.measurement_info.set("标定：请依次点击右图中同平面参照长度的两个端点，间距至少8个实际像素。")
        self.refresh_preview()

    def output_point(self, x, y):
        geometry = getattr(self, "_output_geometry", None)
        if geometry is None:
            return None
        width, height, scale = geometry
        left = (self.output_label.winfo_width() - width * scale) / 2.0
        top = (self.output_label.winfo_height() - height * scale) / 2.0
        px, py = (x - left) / scale, (y - top) / scale
        if not (0 <= px < width and 0 <= py < height):
            return None
        return [float(px), float(py)]

    def measurement_pointer_down(self, event):
        if not self._measurement_snapshot().get("enabled") or self._display_event is None or self._display_event[2]["mode"] != 2:
            return
        point = self.output_point(event.x, event.y)
        if point is None:
            self.measurement_info.set("请点击右侧实际图像内部，黑色留白不属于图像。")
            return
        if self._calibration_pending is not None:
            pending = self._calibration_pending
            pending["points"].append(point)
            if len(pending["points"]) == 1:
                self.measurement_info.set("第一个端点已记录，请点击已知长度的第二个端点。")
                return
            try:
                scale = calibration_scale(*pending["points"], pending["known_mm"])
            except ValueError as exc:
                self._calibration_pending = None
                self.measurement_info.set("标定失败：%s；请重新点击两点标定。" % exc)
                return
            self._update_measurement_settings(mm_per_pixel=scale,
                                              calibration_points=pending["points"],
                                              calibration_known_mm=pending["known_mm"])
            self._calibration_pending = None
            self.measurement_info.set("已标定 %.6f mm/px；等待下一帧毫米估计值。相机及平面改变后须重做。" % scale)
            self.refresh_preview()
        else:
            self._roi_drag_start = point

    def measurement_pointer_up(self, event):
        start = self._roi_drag_start
        self._roi_drag_start = None
        if start is None or self._calibration_pending is not None:
            return
        end = self.output_point(event.x, event.y)
        if end is None:
            self.measurement_info.set("ROI终点在图像外，请在右图内部重新拖框。")
            return
        width, height, _ = self._output_geometry
        roi = [math.floor(min(start[0], end[0])), math.floor(min(start[1], end[1])),
               min(width, math.floor(max(start[0], end[0])) + 1),
               min(height, math.floor(max(start[1], end[1])) + 1)]
        if roi[2] - roi[0] < 8 or roi[3] - roi[1] < 8:
            self.measurement_info.set("ROI过小，请拖出至少8×8实际像素的矩形，留出待测物完整边界。")
            return
        self._update_measurement_settings(roi=roi)
        self.measurement_info.set("ROI已设为%s，等待下一帧；轮廓触及ROI边缘时不输出尺寸。" % roi)
        self.refresh_preview()

    def _measure_verified_frame(self, actual, metrics, case_directory):
        settings = self._measurement_snapshot()
        if not settings.get("enabled") or metrics["mode"] != 2:
            return
        measurement = analyze_edges(actual, roi=settings["roi"], threshold=settings["threshold"],
                                    min_area=settings["min_area"], mm_per_pixel=settings["mm_per_pixel"],
                                    close_gaps=settings.get("close_gaps", True))
        record = dict(schema_version=1, settings_version=settings["version"],
                      source="verified_fpga_sobel", computation="host", frame=metrics["frame"],
                      source_output_shape=list(actual.shape), settings=settings, result=measurement)
        record["source_response_crc32"] = metrics.get("response_crc32")
        overlay = render_measurement_overlay(actual, measurement, settings["calibration_points"])
        (case_directory / "measurement.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        overlay.save(case_directory / "measurement_overlay.png")
        metrics["measurement"] = record

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
        self._reset_measurement_geometry("新会话已清除ROI和标定；请在画面稳定后重新框选与标定。")
        self._display_event = None
        self._output_geometry = None
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
        width, height, _ = resolution_profile(getattr(self.args, "width", WIDTH),
                                               getattr(self.args, "height", HEIGHT))
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
            client = FrameClient(port, baudrate=baud, timeout=self.args.timeout,
                                 width=width, height=height)
            client.open()
            result["firmware_info"] = client.firmware_info
            if stop_event.is_set():
                return
            capture, camera_metadata = open_selected_camera(self.args.camera_name, width=width, height=height)
            result["camera"] = camera_metadata
            result["camera_capture_test"] = True
            self._events.put(("camera", camera_metadata))
            run_started = time.perf_counter()
            index = 0
            while not stop_event.is_set():
                with self._mode_lock:
                    mode = self._mode
                rgb, source_shape, source_rgb = read_camera_rgb(capture, include_source=True,
                                                               width=width, height=height)
                if stop_event.is_set():
                    break
                expected = process_reference(rgb, mode)
                actual, details = client.process(rgb, mode)
                case_directory = directory / ("frame%06d_mode%d" % (index, mode))
                metrics = save_verified_case(case_directory,
                                             rgb, actual, expected, details, index, mode, source_shape)
                result["cases"].append(metrics)
                if not metrics["exact_match"]:
                    raise AssertionError("摄像头实际输入与 FPGA 输出逐像素比较不一致")
                # Geometry always uses the actual completed, independently
                # verified FPGA Sobel response, never the selector or source RGB.
                self._measure_verified_frame(actual, metrics, case_directory)
                result["hardware_test"] = True
                index += 1
                elapsed = time.perf_counter() - run_started
                metrics["verified_loop_frames_per_second"] = index / elapsed
                self._latest_frame((rgb, actual, metrics, str(directory), source_rgb))
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
            result["measurement_frames"] = sum("measurement" in item for item in result["cases"])
            result["measurement_note"] = ("Host contour/minimum bounding rectangle estimation after verified FPGA Sobel. "
                                          "Single scale assumes perpendicular camera and coplanar reference/object; not perspective correction or certified metrology.")
            result["completed_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            if directory is not None:
                try:
                    (directory / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
                except Exception as exc:
                    result["error"] = "结果写入失败: %s" % exc
                    result["camera_test"] = False
                    result["all_modes_verified"] = False
            self._events.put(("finished", (result, str(directory) if directory else None)))

    def refresh_preview(self):
        if self._display_event is not None:
            self.render_frame(self._display_event)

    def render_frame(self, event):
        self._display_event = event
        rgb, actual, metrics, directory, source_rgb = event
        source = metrics["source_bgr_shape"]
        height, width = rgb.shape[:2]
        scale = 512 // width
        if self.show_source.get():
            preview_size = (max(2, self.input_label.winfo_width()),
                            max(2, self.input_label.winfo_height()))
            preview_image = ImageOps.contain(Image.fromarray(source_rgb), preview_size, Image.Resampling.LANCZOS)
            self.input_panel.configure(text="相机原图 %d×%d（FPGA 输入%d×%d）" %
                                       (source[1], source[0], width, height))
        else:
            preview_image = Image.fromarray(rgb).resize((width * scale, height * scale), Image.Resampling.NEAREST)
            self.input_panel.configure(text="送入 FPGA 的 RGB %d×%d（放大%d倍）" % (width, height, scale))
        input_image = ImageTk.PhotoImage(preview_image)
        mode = metrics["mode"]  # Actual completed frame, independent of the current selector.
        self._output_geometry = (actual.shape[1], actual.shape[0], scale)
        settings = self._measurement_snapshot()
        if settings.get("enabled") and mode == 2:
            shape = tuple(actual.shape)
            previous_shape = getattr(self, "_measurement_shape", None)
            if previous_shape is not None and previous_shape != shape:
                self._reset_measurement_geometry("输出尺寸变化，已清除ROI与标定；请重新设置。")
                settings = self._measurement_snapshot()
            self._measurement_shape = shape
        measurement = metrics.get("measurement")
        show_measurement = bool(settings.get("enabled") and mode == 2 and measurement is not None
                                and measurement["settings_version"] == settings["version"])
        output_picture = Image.fromarray(actual)
        if show_measurement:
            output_picture = render_measurement_overlay(actual, measurement["result"],
                                                       measurement["settings"]["calibration_points"])
            self._show_measurement_result(measurement["result"])
        elif settings.get("enabled") and mode == 2 and getattr(self, "_calibration_pending", None) is None:
            self.measurement_info.set("测量参数已更新，等待下一幅匹配参数的已验证边缘图。")
        output_image = ImageTk.PhotoImage(output_picture.resize((actual.shape[1] * scale, actual.shape[0] * scale), Image.Resampling.NEAREST))
        self._photos = [input_image, output_image]
        self.input_label.configure(image=input_image, text="")
        self.output_label.configure(image=output_image, text="")
        self.output_panel.configure(text="FPGA %s，实际输出 %d×%d（放大%d倍）" %
                                    (MODE_TEXT[mode], actual.shape[1], actual.shape[0], scale) +
                                    (" + 电脑端测量叠加" if show_measurement else ""))
        self.metrics.set("帧 %d | 实际模式 %d %s | 像素一致 | UART往返 %.3fs | 已验证处理吞吐 %.2f 帧/秒" %
                         (metrics["frame"], mode, MODE_TEXT[mode], metrics["uart_roundtrip_seconds"],
                          metrics["verified_loop_frames_per_second"]))
        self.evidence.set("实际图像与逐帧结果：" + evidence_display_path(directory))

    def _show_measurement_result(self, measurement):
        if getattr(self, "_calibration_pending", None) is not None:
            return
        if measurement["status"] == "truncated":
            text = "待测外轮廓触及ROI/图像边缘，尺寸无效；请扩大ROI或完整放入待测物。"
        elif measurement["status"] == "no_contour":
            text = "未找到符合面积条件的闭合外轮廓；请用干净背景、调整阈值或框选ROI。"
        elif measurement["long_mm"] is not None:
            text = "最大外轮廓外接矩形估计：长 %.2f mm × 短 %.2f mm（%.1f × %.1f px）；标定 %.6f mm/px。" % (
                measurement["long_mm"], measurement["short_mm"], measurement["long_px"],
                measurement["short_px"], measurement["mm_per_pixel"])
        else:
            text = "最大外轮廓外接矩形：长 %.1f px × 短 %.1f px；尚未标定，不输出毫米值。" % (
                measurement["long_px"], measurement["short_px"])
        self.measurement_info.set(text)

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
    parser.add_argument("--width", type=int, default=WIDTH)
    parser.add_argument("--height", type=int, default=HEIGHT)
    parser.add_argument("--mode", type=int, choices=list(MODES), default=0)
    parser.add_argument("--max-frames", type=nonnegative_frames, default=0,
                        help="Stop and release devices after N verified frames (0: continuous)")
    parser.add_argument("--output-root", type=Path, default=Path(__file__).resolve().parents[1] / "output" / "uart_live")
    args = parser.parse_args()
    try:
        args.width, args.height, _ = resolution_profile(args.width, args.height)
    except ValueError as exc:
        parser.error(str(exc))
    root = tk.Tk()
    LiveDemo(root, args)
    root.mainloop()


if __name__ == "__main__":
    main()
