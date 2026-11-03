"""Visible live preview of the explicitly selected external MF200 camera."""
import argparse
import datetime
import json
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk

import cv2
from PIL import Image, ImageOps, ImageTk


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--camera-name', default='MF200 Camera')
    parser.add_argument('--powershell', default=shutil.which('pwsh'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.powershell:
        raise RuntimeError('PowerShell path is required for explicit camera selection')
    args.output.mkdir(parents=True, exist_ok=False)
    events = queue.Queue(maxsize=2)
    stop = threading.Event()
    report = dict(camera_name=args.camera_name, preview_only=True,
                  fpga_processing=False, camera_released=False, frames=0,
                  started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    root = tk.Tk()
    root.title('MF200 摄像头实时画面')
    root.geometry('900x700')
    root.minsize(680, 540)
    root.configure(background='#f5f6f8')
    frame = ttk.Frame(root, padding=12)
    frame.pack(fill='both', expand=True)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(2, weight=1)
    ttk.Label(frame, text='MF200 摄像头实时画面',
              font=('Microsoft YaHei UI', 16, 'bold')).grid(row=0, column=0, sticky='w')
    ttk.Label(frame, text='摄像头原图预览',
              font=('Microsoft YaHei UI', 10)).grid(row=1, column=0, sticky='w', pady=(3, 8))
    video_area = tk.Frame(frame, background='#19232b', width=800, height=480)
    video_area.grid(row=2, column=0, sticky='nsew')
    video_area.grid_propagate(False)
    video = tk.Label(video_area, background='#19232b', foreground='white',
                     borderwidth=0, text='正在连接摄像头…')
    video.place(relx=0.5, rely=0.5, anchor='center')
    status = tk.StringVar(value='正在识别 MF200 Camera')
    ttk.Label(frame, textvariable=status, font=('Microsoft YaHei UI', 10)).grid(row=3, column=0, sticky='w', pady=8)
    controls = ttk.Frame(frame)
    controls.grid(row=4, column=0, sticky='ew')
    paused = False
    closing = False
    last_rgb = None
    photo = None

    def publish(item):
        try:
            events.put_nowait(item)
        except queue.Full:
            try:
                events.get_nowait()
            except queue.Empty:
                pass
            events.put_nowait(item)

    def worker():
        cap = None
        try:
            helper = Path(__file__).with_name('list_windows_cameras.ps1')
            query = subprocess.run([args.powershell, '-NoProfile', '-File', str(helper)],
                                   capture_output=True, check=True, encoding='utf-8-sig', timeout=20)
            devices = json.loads(query.stdout)
            candidates = [d for d in devices if d['name'] == args.camera_name
                          and 'vid_0c45' in d['path'].lower() and 'pid_6366' in d['path'].lower()]
            if len(candidates) != 1:
                raise RuntimeError('未找到唯一的 MF200 摄像头，请检查连接')
            selected = candidates[0]
            cap = cv2.VideoCapture(selected['index'], cv2.CAP_DSHOW)
            if not cap.isOpened():
                raise RuntimeError('无法打开 MF200 摄像头，可能正被其他程序使用')
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            started = time.monotonic()
            report['device_index'] = selected['index']
            while not stop.is_set():
                ok, bgr = cap.read()
                if not ok or bgr is None:
                    raise RuntimeError('摄像头读取中断，请检查 USB 连接')
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                report['frames'] += 1
                report['source_shape'] = list(rgb.shape)
                fps = report['frames'] / max(0.001, time.monotonic() - started)
                publish(('frame', rgb, fps))
        except Exception as exc:
            report['error'] = type(exc).__name__ + ': ' + str(exc)
            publish(('error', str(exc)))
        finally:
            if cap is not None:
                cap.release()
            report['camera_released'] = True
            report['completed_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            (args.output / 'session.json').write_text(json.dumps(report, indent=2), encoding='utf-8')

    def toggle_pause():
        nonlocal paused
        paused = not paused
        pause_button.configure(text='继续预览' if paused else '暂停画面')
        if paused:
            status.set('画面已暂停，点击“继续预览”恢复')

    def snapshot():
        if last_rgb is not None:
            name = 'snapshot_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.png'
            Image.fromarray(last_rgb).save(args.output / name)
            status.set('已保存当前画面')

    def close():
        nonlocal closing
        if closing:
            return
        closing = True
        stop.set()
        status.set('正在关闭摄像头…')
        close_deadline = time.monotonic() + 3

        def finish():
            if not thread.is_alive() or time.monotonic() >= close_deadline:
                root.destroy()
            else:
                root.after(50, finish)
        finish()

    pause_button = ttk.Button(controls, text='暂停画面', command=toggle_pause)
    pause_button.pack(side='left')
    ttk.Button(controls, text='保存当前画面', command=snapshot).pack(side='left', padx=8)
    ttk.Button(controls, text='关闭预览', command=close).pack(side='right')
    root.protocol('WM_DELETE_WINDOW', close)

    def refresh():
        nonlocal last_rgb, photo
        if closing:
            return
        latest = None
        try:
            while True:
                latest = events.get_nowait()
        except queue.Empty:
            pass
        if latest is not None:
            if latest[0] == 'error':
                status.set(latest[1])
            elif not paused:
                _, last_rgb, fps = latest
                picture = ImageOps.contain(Image.fromarray(last_rgb),
                                          (max(2, video_area.winfo_width()), max(2, video_area.winfo_height())),
                                          Image.Resampling.BILINEAR)
                photo = ImageTk.PhotoImage(picture)
                video.configure(image=photo, text='')
                status.set('MF200 Camera · %d×%d · 预览 %.1f 帧/秒' %
                           (last_rgb.shape[1], last_rgb.shape[0], fps))
        root.after(30, refresh)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    root.after(30, refresh)
    root.mainloop()
    stop.set()
    thread.join(timeout=3)


if __name__ == '__main__':
    main()
