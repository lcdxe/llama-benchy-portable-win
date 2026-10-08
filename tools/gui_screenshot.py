"""Render the GUI and save screenshots for the README.

Needs Pillow (pip install pillow). Run from the project root:

    python tools/gui_screenshot.py --outdir docs/screenshots

The script builds the real tkinter panel in-process, switches tabs and opens
the preset editor, then grabs the window rectangle from the screen. It does not
contact any inference server.
"""

import argparse
import json
import os
import sys
import time

import tkinter as tk
from tkinter import ttk

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(APP_DIR)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "gui"))

from PIL import ImageGrab  # noqa: E402  (import after path setup)
import bench_gui  # noqa: E402


DEMO_PRESETS = [
    {
        "name": "单流速度", "base_url": "http://127.0.0.1:8080/v1", "api_key": "",
        "model": "demo-model", "served_model_name": "", "tokenizer": "",
        "pp": "512", "tg": "128", "depth": "512 4096", "concurrency": "",
        "runs": "2", "warmup_runs": "", "latency_mode": "generation",
        "prefix_caching": False, "no_cache": False, "exact_tg": True,
        "skip_coherence": False, "no_warmup": False, "no_adapt_prompt": False,
        "exit_on_fail": False, "ts_total": False, "ts_all": False,
        "pre_cmd": "", "post_cmd": "", "extra_body": "", "book_url": "",
        "format": "json", "wait_port": True, "enabled": True,
    },
    {
        "name": "并发测试", "base_url": "http://127.0.0.1:8080/v1", "api_key": "",
        "model": "demo-model", "served_model_name": "", "tokenizer": "",
        "pp": "512", "tg": "64", "depth": "512", "concurrency": "4",
        "runs": "3", "warmup_runs": "", "latency_mode": "generation",
        "prefix_caching": False, "no_cache": False, "exact_tg": True,
        "skip_coherence": False, "no_warmup": False, "no_adapt_prompt": False,
        "exit_on_fail": False, "ts_total": False, "ts_all": False,
        "pre_cmd": "", "post_cmd": "", "extra_body": "", "book_url": "",
        "format": "json", "wait_port": True, "enabled": True,
    },
    {
        "name": "缓存命中", "base_url": "http://127.0.0.1:8080/v1", "api_key": "",
        "model": "demo-model", "served_model_name": "", "tokenizer": "",
        "pp": "", "tg": "", "depth": "8192", "concurrency": "",
        "runs": "2", "warmup_runs": "", "latency_mode": "generation",
        "prefix_caching": True, "no_cache": False, "exact_tg": True,
        "skip_coherence": False, "no_warmup": False, "no_adapt_prompt": False,
        "exit_on_fail": False, "ts_total": False, "ts_all": False,
        "pre_cmd": "", "post_cmd": "", "extra_body": "", "book_url": "",
        "format": "json", "wait_port": True, "enabled": True,
    },
]

# mtp3..mtp6 templates: same shape as the built-in ones, with a pre-command that
# restarts the server with a different speculative-decoding setting.
for i in (3, 4, 5, 6):
    DEMO_PRESETS.append(dict(
        DEMO_PRESETS[0], name=f"mtp{i}", pp="512", tg="128", depth="512 4096",
        runs="3", pre_cmd=f"restart_mtp{i}.bat", enabled=(i <= 5),
    ))


def window_rect(title):
    """Screen rectangle of a top-level window by title (physical pixels)."""
    import ctypes

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return None
    r = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def capture(path, *windows, bbox=None):
    if bbox is None:
        x1, y1, x2, y2 = [], [], [], []
        for w in windows:
            w.update_idletasks()
            x1.append(w.winfo_rootx())
            y1.append(w.winfo_rooty())
            x2.append(w.winfo_rootx() + w.winfo_width())
            y2.append(w.winfo_rooty() + w.winfo_height())
        bbox = (min(x1), min(y1), max(x2), max(y2))
    img = ImageGrab.grab(bbox=bbox)
    img.save(path)
    print(f"saved {path}  ({img.size[0]}x{img.size[1]})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="docs/screenshots")
    ap.add_argument("--batch", default=os.path.join(ROOT, "gui", "batch.json"))
    ap.add_argument("--no-batch", action="store_true",
                    help="do not write the demo preset file")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    if not args.no_batch:
        with open(args.batch, "w", encoding="utf-8") as f:
            json.dump(DEMO_PRESETS, f, ensure_ascii=False, indent=2)

    root = tk.Tk()
    try:
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)
        ctypes.windll.user32.ReleaseDC(0, hdc)
        if dpi and dpi > 96:
            root.tk.call("tk", "scaling", dpi / 96.0)
    except Exception:
        pass

    gui = bench_gui.BenchGUI(root)
    root.update_idletasks()
    root.update()
    time.sleep(1.2)

    capture(os.path.join(args.outdir, "gui-presets.png"), root)

    gui.nb.select(gui.tab_cmp)
    gui._refresh_files()
    gui._select_all_files()
    gui._rebuild_compare()
    root.update_idletasks()
    root.update()
    time.sleep(1.2)
    capture(os.path.join(args.outdir, "gui-compare.png"), root)

    gui.nb.select(gui.tab_batch)
    root.update_idletasks()
    root.update()
    time.sleep(0.6)
    gui._batch_edit(0)
    root.update_idletasks()
    root.update()
    time.sleep(1.2)
    rect = window_rect("编辑预设 - 单流速度")
    if rect:
        capture(os.path.join(args.outdir, "gui-preset-editor.png"), bbox=rect)
        import ctypes
        hwnd = ctypes.windll.user32.FindWindowW(None, "编辑预设 - 单流速度")
        if hwnd:
            ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
    else:
        print("preset editor window not found, skipping")

    root.destroy()


if __name__ == "__main__":
    main()
