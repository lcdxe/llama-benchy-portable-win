#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
llama-benchy GUI - 绿色便携版
单文件 tkinter 应用，仅用标准库（零外部依赖，离线可用）。

功能:
  * 测试页: 快速调参(全参数表单 + 预设), 一键运行 llama-benchy(子进程),
             结果自动保存到 results\<模型名>\<名称>.json (按 --model 分目录; 同名文件不覆盖: 已存在时自动改用 <名称>_2.json, <名称>_3.json …); 运行时弹出独立控制台窗口实时显示输出,
             命令/退出码记录在 gui\runs\<名称>_<时间>.log
  * 预设页: 命名预设列表(gui\batch.json), 每个预设 = 一种服务器配置(如 MTP N);
             选中 → 「运行该预设」逐个手动运行(前置命令可选, 用于自动重启/切换服务器),
             结果自动存 results\<模型名>\<名称>.json; 跑完到对比页多选合并对比
  * 对比页: 加载多份已保存的 JSON 结果, 按测试形状合并对比表(含相对基线的 Δ%),
             基线可选, 折线/柱状图, 导出对比 CSV; 勾选后可「删除选中」结果文件(先备份到 results\deleted\)

用法: GUI.bat 或 python\\python.exe gui\\bench_gui.py
"""
import csv
import datetime as _dt
import json
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from tkinter import font as tkfont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui_theme import (apply_theme, style_dialog, detect_display, set_scale,
                      BG, BG_PANEL, BG_FIELD, BG_HEAD, BORDER,
                      FG, FG_DIM, ACCENT, GOOD, BAD, CHART_COLORS, CHART_LINE_WIDTH,
                      FONT as _UI_FONT, FONT_BOLD, FONT_MONO)

APP_DIR = os.path.dirname(os.path.abspath(__file__))   # gui/ (bundle or repo)
GREEN_DIR = os.path.dirname(APP_DIR)                   # bundle root / repo root

# Interpreter lookup: bundled portable runtime -> bootstrap-created .venv ->
# whatever python is running this GUI. Keeps the GUI usable for plain clones.
_BUNDLED_PY = os.path.join(GREEN_DIR, "python", "python.exe")
_VENV_PY = os.path.join(GREEN_DIR, ".venv", "Scripts", "python.exe")
if os.path.isfile(_BUNDLED_PY):
    PYTHON_EXE = _BUNDLED_PY
elif os.path.isfile(_VENV_PY):
    PYTHON_EXE = _VENV_PY
else:
    PYTHON_EXE = sys.executable

_BUNDLED_SRC = os.path.join(GREEN_DIR, "llama-benchy")
SRC_DIR = _BUNDLED_SRC if os.path.isdir(os.path.join(_BUNDLED_SRC, "llama_benchy")) else GREEN_DIR
RESULTS_DIR = os.path.join(GREEN_DIR, "results")

BATCH_FILE = os.path.join(APP_DIR, "batch.json")
RUNS_DIR = os.path.join(APP_DIR, "runs")          # 每次运行的完整/故障日志

FONT = _UI_FONT
COLORS = CHART_COLORS   # 深色主题下的高对比系列色(见 ui_theme.py)

# 手动覆盖自动探测的界面缩放(相对 11 号基准字)
SCALE_PRESETS = {"自动": None, "小": 0.78, "标准": 1.0, "大": 1.18}


def _sync_fonts():
    """ui_theme.set_scale() 改的是 ui_theme 里的常量; 把本模块的引用同步过去。"""
    global FONT, _UI_FONT, FONT_BOLD, FONT_MONO
    import ui_theme
    FONT = _UI_FONT = ui_theme.FONT
    FONT_BOLD = ui_theme.FONT_BOLD
    FONT_MONO = ui_theme.FONT_MONO

# ---------------------------------------------------------------- 预设 ----

DEFAULT_PRESETS = {
    "单流速度": dict(
        base_url="http://127.0.0.1:8080/v1", api_key="", model="qwen38",
        served_model_name="", tokenizer="",
        pp="512", tg="512", depth="512 4096 8096", concurrency="",
        runs="3", warmup_runs="",
        latency_mode="generation", prefix_caching=False, no_cache=False,
        exact_tg=True, skip_coherence=False, no_warmup=False,
        no_adapt_prompt=False, exit_on_fail=False, ts_total=False, ts_all=False,
        pre_cmd="", post_cmd="", extra_body="", book_url="", format="json",
        wait_port=True, enabled=True),
    "并发测试": dict(
        base_url="http://127.0.0.1:8080/v1", api_key="", model="qwen38",
        served_model_name="", tokenizer="",
        pp="512", tg="128", depth="512 4096 8096 16384", concurrency="4",
        runs="2", warmup_runs="",
        latency_mode="generation", prefix_caching=False, no_cache=False,
        exact_tg=True, skip_coherence=False, no_warmup=False,
        no_adapt_prompt=False, exit_on_fail=False, ts_total=False, ts_all=False,
        pre_cmd="", post_cmd="", extra_body="", book_url="", format="json",
        wait_port=True, enabled=True),
    "缓存命中": dict(
        base_url="http://127.0.0.1:8080/v1", api_key="", model="qwen38",
        served_model_name="", tokenizer="",
        pp="", tg="", depth="32768 65536", concurrency="",
        runs="3", warmup_runs="",
        latency_mode="generation", prefix_caching=True, no_cache=False,
        exact_tg=True, skip_coherence=False, no_warmup=False,
        no_adapt_prompt=False, exit_on_fail=False, ts_total=False, ts_all=False,
        pre_cmd="", post_cmd="", extra_body="", book_url="", format="json",
        wait_port=True, enabled=True),
}

_SINGLE_STREAM = dict(DEFAULT_PRESETS["单流速度"])
DEFAULT_BATCH = [dict(_SINGLE_STREAM, name=f"mtp{i}", pre_cmd="")
                 for i in (3, 4, 5, 6)]

# ---------------------------------------------------------------- 解析 ----

METRIC_FIELDS = [
    ("pp t/s", "pp_throughput"),
    ("pp t/s (req)", "pp_req_throughput"),
    ("tg t/s", "tg_throughput"),
    ("tg t/s (req)", "tg_req_throughput"),
    ("peak t/s", "peak_throughput"),
    ("ttfr (ms)", "ttfr"),
    ("est_ppt (ms)", "est_ppt"),
    ("e2e_ttft (ms)", "e2e_ttft"),
]

# 每个指标对应的右侧解释(随指标下拉切换实时更新)
# 口径: 不带 (req) 的是单流速度; 带 (req) 的是所有并发合计(越高越好)
METRIC_EXPLAIN = {
    "pp_throughput": "pp t/s：单流预填充速度——一次请求处理输入(prompt)时，每秒能读入多少 token。越高越好。",
    "pp_req_throughput": "pp t/s (req)：所有并发合计的预填充吞吐。并发越多合计越高，反映服务器整体处理能力。越高越好。",
    "tg_throughput": "tg t/s：单流生成速度——一次请求逐 token 输出时，每秒能生成多少 token。越高越好。",
    "tg_req_throughput": "tg t/s (req)：所有并发合计的生成吞吐。并发越多合计越高，反映服务器整体处理能力。越高越好。",
    "peak_throughput": "peak t/s：所有并发合计的峰值吞吐，取测试期间最高瞬时值。越高越好。",
    "ttfr": "ttfr：单个 token 的平均生成时间(ms)，越低越好。注意它是逐 token 耗时，不是首 token 总耗时——128K 显示 242ms 属正常。",
    "est_ppt": "est_ppt：单个 token 的平均预填充时间(ms)，越低越好。",
    "e2e_ttft": "e2e_ttft：端到端首 token 总耗时(ms)——从发出请求到收到第一个 token，含排队与预填充。越低越好。",
}

_META_KEYS = ("version", "timestamp", "latency_mode", "latency_ms",
              "model", "prefix_caching_enabled", "max_concurrency")

_MS_FIELDS = {"ttfr", "est_ppt", "e2e_ttft"}


def fmt_ms(v):
    """毫秒值格式化: 一律保留 ms(数据本身就是毫秒值, 不做 s 换算, 避免误读)。"""
    if v is None:
        return "—"
    return f"{v:.1f} ms"


def parse_report_data(data):
    """把一份 --save-result 保存的 JSON 解析为 (meta, rows)。
    row: {name, family, depth, size, metrics:{field:(mean,std)}}
    行命名与程序 md 表格完全一致(pp512 @ d4096 / ctx_pp @ d32768 ...)。"""
    meta = {k: data.get(k) for k in _META_KEYS}
    maxc = meta.get("max_concurrency") or 1
    rows = []

    def add(name, family, b):
        m = {}
        for _label, field in METRIC_FIELDS:
            v = b.get(field)
            if isinstance(v, dict) and v.get("mean") is not None:
                m[field] = (float(v["mean"]), float(v.get("std", 0.0)))
        mm = re.match(r"(?:ctx_)?(?:pp|tg)(\d+)", name)
        rows.append({
            "name": name, "family": family, "depth": int(b.get("context_size", 0)),
            "size": int(mm.group(1)) if mm else None, "metrics": m,
        })

    for b in data.get("benchmarks", []):
        c = f" (c{b['concurrency']})" if maxc > 1 else ""
        ctx = int(b.get("context_size", 0))
        if b.get("is_context_prefill_phase"):
            if b.get("pp_throughput"):
                add(f"ctx_pp @ d{ctx}{c}", "ctx_pp", b)
            if b.get("tg_throughput") or b.get("peak_throughput"):
                add(f"ctx_tg @ d{ctx}{c}", "ctx_tg", b)
        else:
            ds = f" @ d{ctx}" if ctx > 0 else ""
            if b.get("pp_throughput"):
                add(f"pp{b['prompt_size']}{ds}{c}", "pp", b)
            if b.get("tg_throughput") or b.get("peak_throughput"):
                add(f"tg{b['response_size']}{ds}{c}", "tg", b)
    return meta, rows


def load_report(path, label=None):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    label = label or os.path.splitext(os.path.basename(path))[0]
    return label, *parse_report_data(data)


def fmt_val(field, v):
    """按指标格式化: 毫秒类指标保留 ms(数据即毫秒, 不换算成秒), 吞吐类保留 2 位小数。"""
    if v is None:
        return "—"
    if field in _MS_FIELDS:
        return fmt_ms(v)
    return f"{v:.2f}"


# ---------------------------------------------------------------- 命令 ----

def model_dir(model):
    """按模型名建子目录 results\\<model>\\；模型名为空时用「未命名模型」。"""
    m = re.sub(r'[\\/:*?"<>|]', "_", (model or "").strip()) or "未命名模型"
    return os.path.join(RESULTS_DIR, m)


def result_base_dir(p):
    """本次运行结果应存放的目录: 按 --model(或 served_model_name) 分目录。"""
    return model_dir(p.get("model", "") or p.get("served_model_name", ""))


def unique_result_path(name, ext, base_dir=None):
    """结果保存路径: 同名文件不覆盖旧文件, 依次尝试 <名称>, <名称>_2, <名称>_3 …"""
    base = base_dir or RESULTS_DIR
    safe = re.sub(r'[\\/:*?"<>|]', "_", name)
    path = os.path.join(base, safe + ext)
    k = 2
    while os.path.exists(path):
        path = os.path.join(base, f"{safe}_{k}{ext}")
        k += 1
    return path


def iter_result_files():
    """列出 results\\ 下(含按模型建的子目录)所有 json 结果，跳过 deleted\\ 备份。"""
    out = []
    if not os.path.isdir(RESULTS_DIR):
        return out
    for root, dirs, files in os.walk(RESULTS_DIR):
        dirs[:] = [d for d in dirs if d.lower() != "deleted"]
        for fn in files:
            if fn.lower().endswith(".json"):
                out.append(os.path.join(root, fn))
    return out


def migrate_legacy_results():
    """把 results\\ 根目录里的旧结果文件移入 results\\<model>\\ 子目录。
    模型名取自 JSON 的 model 字段；取不到则归入「未命名模型」。返回迁移条数。"""
    n = 0
    for fn in sorted(os.listdir(RESULTS_DIR)) if os.path.isdir(RESULTS_DIR) else []:
        src = os.path.join(RESULTS_DIR, fn)
        if not os.path.isfile(src) or not fn.lower().endswith((".json", ".md", ".csv")):
            continue
        model = ""
        if fn.lower().endswith(".json"):
            try:
                with open(src, "r", encoding="utf-8") as f:
                    model = (json.load(f).get("model") or "").strip()
            except (OSError, ValueError):
                model = ""
        base = model_dir(model)
        try:
            os.makedirs(base, exist_ok=True)
            dst = unique_result_path(os.path.splitext(fn)[0], os.path.splitext(fn)[1], base)
            shutil.move(src, dst)
            n += 1
        except OSError:
            continue
    return n


def build_argv(p):
    """参数 dict -> llama_benchy 命令行参数列表(不含解释器)。"""
    a = ["-m", "llama_benchy", "--base-url", p["base_url"].strip()]
    if p.get("api_key", "").strip():
        a += ["--api-key", p["api_key"].strip()]
    if p.get("model", "").strip():
        a += ["--model", p["model"].strip()]
    if p.get("served_model_name", "").strip():
        a += ["--served-model-name", p["served_model_name"].strip()]
    if p.get("tokenizer", "").strip():
        a += ["--tokenizer", p["tokenizer"].strip()]
    for key, flag in (("pp", "--pp"), ("tg", "--tg"),
                      ("depth", "--depth"), ("concurrency", "--concurrency")):
        vals = [v for v in p.get(key, "").split() if v]
        if vals:
            a += [flag] + vals
    if p.get("runs", "").strip():
        a += ["--runs", p["runs"].strip()]
    if p.get("warmup_runs", "").strip():
        a += ["--warmup-runs", p["warmup_runs"].strip()]
    a += ["--latency-mode", p.get("latency_mode", "generation")]
    if p.get("prefix_caching"):
        a.append("--enable-prefix-caching")
    if p.get("no_cache"):
        a.append("--no-cache")
    if p.get("exact_tg"):
        a.append("--exact-tg")
    if p.get("skip_coherence"):
        a.append("--skip-coherence")
    if p.get("no_warmup"):
        a.append("--no-warmup")
    if p.get("no_adapt_prompt"):
        a.append("--no-adapt-prompt")
    if p.get("exit_on_fail"):
        a.append("--exit-on-first-fail")
    if p.get("no_results_on_fail"):
        a.append("--no-results-on-fail")
    if p.get("extra_body", "").strip():
        a += ["--extra-body", p["extra_body"].strip()]
    if p.get("book_url", "").strip():
        a += ["--book-url", p["book_url"].strip()]
    if p.get("post_cmd", "").strip():
        a += ["--post-run-cmd", p["post_cmd"].strip()]
    if p.get("ts_total"):
        a.append("--save-total-throughput-timeseries")
    if p.get("ts_all"):
        a.append("--save-all-throughput-timeseries")
    name = p.get("result_name", "").strip()
    if name:
        ext = {"json": ".json", "md": ".md", "csv": ".csv"}[p.get("format", "json")]
        base = result_base_dir(p)
        try:
            os.makedirs(base, exist_ok=True)
        except OSError:
            base = RESULTS_DIR
        path = unique_result_path(name, ext, base)
        p["result_path"] = path          # 实际保存路径(完成提示按此显示)
        a += ["--save-result", path,
              "--format", p.get("format", "json")]
    return a


def expected_points(p):
    """估算测试点数量(笛卡尔积 depth×pp×tg×concurrency)。
    留空时按上游默认: pp=[2048] tg=[32] depth=[0] concurrency=[1]。"""
    def cnt(key, default):
        vals = [v for v in (p.get(key) or "").split() if v]
        return len(vals) or len(default)
    return (cnt("pp", [2048]) * cnt("tg", [32]) * cnt("depth", [0])
            * cnt("concurrency", [1]))


def port_open(host, port, timeout=1.5):
    s = socket.socket()
    s.settimeout(timeout)
    try:
        return s.connect_ex((host, int(port))) == 0
    finally:
        s.close()


# ---------------------------------------------------------------- GUI ----

class BenchGUI:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.proc = None
        self.preproc = None
        self.batch_mode = False   # 批量运行标记: 批量时抑制每个预设的单独弹窗
        self.cmp = None          # 当前对比模型 {labels, rows, meta}
        self._model_queries = {}  # token -> (目标变量, 按钮): 查询服务端模型名的在途请求
        root.title("llama-benchy 控制台 - 绿色便携版 v2")
        # ---- 分辨率自适应 ----------------------------------------------------
        # Tk 坐标是物理像素, 系统缩放(125%/150%)会让控件按 DPI 放大; 固定
        # 1140x780 的窗口在 2K/1080p 上装不下内容(被裁切), 在 4K 上又偏小。
        # 所以: 先探测屏幕 -> 按屏幕"逻辑分辨率"缩放字号 -> 窗口与内部高度
        # 都按目标高度推导, 而不是写死像素。
        self.sc, self.k, self.lw, self.lh = detect_display(root)
        self._auto_k = self.k
        self.fs = set_scale(self.k)
        _sync_fonts()
        apply_theme(root, self.k)
        self._sw = root.winfo_screenwidth()
        self._sh = root.winfo_screenheight()
        self._target_w = max(720, min(int(1660 * self.sc * self.k), self._sw - 60))
        self._target_h = max(520, min(int(1200 * self.sc * self.k), self._sh - 60))
        root.geometry(f"{self._target_w}x{self._target_h}")
        root.minsize(max(620, int(self._target_w * 0.55)), max(420, int(self._target_h * 0.55)))
        self.var_scale = tk.StringVar(value="自动")
        try:
            root.option_add("*Font", _UI_FONT)
        except tk.TclError:
            pass

        self.nb = ttk.Notebook(root)
        self.nb.pack(fill="both", expand=True, padx=8, pady=8)
        self.tab_batch = ttk.Frame(self.nb)
        self.tab_cmp = ttk.Frame(self.nb)
        self.nb.add(self.tab_batch, text=" 预设 ")
        self.nb.add(self.tab_cmp, text=" 对比 ")

        self._build_batch_tab()
        self._build_compare_tab()

        self.sbar = sbar = ttk.Frame(root)
        sbar.pack(fill="x", side="bottom")
        self.pbar = ttk.Progressbar(sbar, mode="indeterminate", length=180)
        self.pbar.pack(side="left", padx=(8, 6))
        self.status = ttk.Label(sbar, text="就绪", style="Status.TLabel")
        self.status.pack(side="left", fill="x", expand=True)
        # 界面缩放: 自动按分辨率算, 也可以手动覆盖(多显示器/特殊缩放时)
        self.cb_scale = ttk.Combobox(sbar, textvariable=self.var_scale, width=7, state="readonly",
                                     values=list(SCALE_PRESETS))
        self.cb_scale.pack(side="right")
        self.cb_scale.bind("<<ComboboxSelected>>", self._apply_scale)
        ttk.Label(sbar, text="界面缩放:", style="Dim.TLabel").pack(side="right", padx=(8, 2))
        self.root.after(100, self._poll_queue)

        self.batch = self._load_batch()
        self._render_batch()

        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self._refresh_files()      # 启动即加载已保存的结果
        self._fit_layout()         # 按屏幕分辨率最终确定窗口与内部高度










    # ---------------------------------------------------------- 运行 ----





    def _set_running(self, running):
        st = "disabled" if running else "normal"
        self.btn_preset_run.configure(state=st)
        self.btn_batch_stop.configure(state="normal" if running else "disabled")
        if running:
            self.pbar.start(12)
        else:
            self.pbar.stop()

    def on_stop(self):
        if self.preproc is not None:
            try:
                self.preproc.kill()
            except OSError:
                pass
            self.q.put(("line", "[GUI] 已发送终止信号(前置命令)"))
        if self.proc is not None:
            try:
                self.proc.kill()
            except OSError:
                pass
            self.q.put(("line", "[GUI] 已发送终止信号(测试进程)"))

    @staticmethod
    def _make_env():
        # 环境变量隔离(与 bat 一致: 禁代理 + HF 离线)
        env = os.environ.copy()
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            env.pop(k, None)
        env["NO_PROXY"] = "localhost,127.0.0.1"
        env["no_proxy"] = "localhost,127.0.0.1"
        env["HF_HUB_OFFLINE"] = "1"
        env["HF_HOME"] = os.path.join(GREEN_DIR, ".hf")
        env["PYTHONPATH"] = SRC_DIR
        return env

    def _wait_port(self, p):
        if not p.get("wait_port", True):
            return True
        try:
            u = urlparse(p["base_url"])
            host = u.hostname or "127.0.0.1"
            port = u.port or (443 if u.scheme == "https" else 80)
        except ValueError:
            host, port = "127.0.0.1", 8080
        for i in range(60):
            try:
                if port_open(host, port):
                    return True
            except OSError:
                pass
            self.q.put(("line", f"Waiting for server {host}:{port} ... check {i + 1}/60"))
            time.sleep(2)
        self.q.put(("line", f"服务 {host}:{port} 未就绪，已取消。"))
        return False

    def _open_run_log(self, name):
        os.makedirs(RUNS_DIR, exist_ok=True)
        safe = re.sub(r'[\\/:*?"<>|]', "_", (name or "").strip() or "run")
        path = os.path.join(RUNS_DIR, f"{safe}_{_dt.datetime.now():%Y%m%d_%H%M%S}.log")
        return open(path, "w", encoding="utf-8", errors="replace"), path

    def _run_one(self, p, env=None, log=None):
        """执行一个配置: 弹出独立控制台窗口实时显示输出(进程结束自动关闭)。
        返回 (退出码, 故障日志路径); 日志记录命令/起止时间/退出码。"""
        argv = build_argv(p)

        def bail(msg):
            if log is not None:
                log[0].write(msg + "\n")
                log[0].close()
            return -1, log[1] if log else None

        if not self._wait_port(p):
            return bail("服务未就绪，已取消。请先启动推理服务。")
        if p.get("result_name", "").strip():
            try:
                os.makedirs(RESULTS_DIR, exist_ok=True)
            except OSError as e:
                return bail(f"创建 results 目录失败: {e}")
        if env is None:
            env = self._make_env()
        if log is None:
            log = self._open_run_log(p.get("result_name", "") or "run")
        f, path = log
        cmd_line = "python\\python.exe " + " ".join(argv)
        f.write(f"开始: {_dt.datetime.now():%Y-%m-%d %H:%M:%S}\n$ {cmd_line}\n")
        f.flush()
        self.q.put(("line", "测试运行中, 输出见弹出的控制台窗口…"))
        try:
            proc = subprocess.Popen(
                [PYTHON_EXE] + argv, cwd=GREEN_DIR, env=env,
                creationflags=subprocess.CREATE_NEW_CONSOLE)
        except OSError as e:
            f.write(f"启动失败: {e}\n")
            f.close()
            return -1, path
        self.proc = proc
        code = proc.wait()
        self.proc = None
        f.write(f"结束: {_dt.datetime.now():%Y-%m-%d %H:%M:%S}  退出码: {code}\n")
        f.close()
        return code, path

    def _poll_queue(self):
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == "line":
                    self.status.configure(text=f"运行中… {item[1][:120]}")
                elif kind == "bstat":
                    self.status.configure(text=item[1])
                    m = item[1]
                    if m.startswith("批量运行完成"):
                        messagebox.showinfo("预设", f"批量运行完成\n{m}")
                    elif m.startswith("批量中止"):
                        messagebox.showerror("预设", f"批量中止\n{m}")
                elif kind == "exit":
                    code, msg, logpath = item[1], item[2], item[3]
                    self._set_running(False)
                    in_batch = getattr(self, "batch_mode", False)
                    if code == 0:
                        self._refresh_files()
                        self.status.configure(text=f"完成 ✓ {msg}")
                        if not in_batch:
                            messagebox.showinfo("预设", f"运行完成\n{msg}")
                    else:
                        tail = f"  故障日志: {logpath}" if logpath else ""
                        self.status.configure(text=msg + tail)
                        if not in_batch:
                            messagebox.showerror("运行失败", msg + tail)
                elif kind == "models":
                    token, (st, payload) = item[1], item[2]
                    entry = self._model_queries.pop(token, None)
                    if entry is None:
                        continue
                    var, btn = entry
                    if st == "ok":
                        self._on_models_result(payload, var, btn)
                    else:
                        self._on_models_err(payload, var, btn)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    # ---------------------------------------------------------- 对比页 ----

    def _adaptive_heights(self):
        """按目标窗口高度推导: 勾选区高 / 图表高 / 表格行数。

        固定部分(工具栏、筛选、控件、表头、状态栏)随字体线性增长, 其余空间
        分配给勾选列表、表格和图表 —— 这样 1080p 也能完整显示, 4K 也不浪费。
        """
        h = self._target_h
        try:
            ls = tkfont.Font(font=_UI_FONT).metrics("linespace")
        except Exception:
            ls = 16
        rowh = int(ttk.Style(self.root).lookup("Treeview", "rowheight") or 30)
        fixed = 7 * (ls + 12)                       # 7 行固定控件
        cb_h = max(56, min(200, int(h * 0.16)))
        chart_h = max(170, min(420, int(h * 0.32)))
        rows = (h - fixed - cb_h - chart_h) // rowh
        return cb_h, chart_h, max(3, min(12, rows))

    def _fit_layout(self):
        """实测"不可压缩"的固定开销, 把剩余高度分配给 勾选区 / 表格 / 图表,
        最后把窗口设为 min(内容自然尺寸, 屏幕-40)。这样 1080p 不裁切, 4K 不浪费。"""
        root = self.root
        root.update_idletasks()
        rowh = int(ttk.Style(root).lookup("Treeview", "rowheight") or 30)
        strip = max(24, self.nb.winfo_reqheight() - max(self.tab_cmp.winfo_reqheight(),
                                                        self.tab_batch.winfo_reqheight()))
        rows_now = int(self.tree["height"])
        fixed = (self.top_frame.winfo_reqheight() + self.filt_frame.winfo_reqheight()
                 + self.cb_canvas.winfo_reqheight() + self.lbl_meta.winfo_reqheight()
                 + self.ctl_frame.winfo_reqheight() + self.lbl_explain.winfo_reqheight()
                 + (self.tree_frame.winfo_reqheight() - rows_now * rowh)
                 + (self.chart_frame.winfo_reqheight() - self.canvas.winfo_reqheight())
                 + self.sbar.winfo_reqheight() + strip)
        h = self._target_h
        cb_h = max(48, min(200, int(h * 0.13)))
        chart_h = max(150, min(420, int(h * 0.28)))
        rows = max(2, min(14, (h - fixed - cb_h - chart_h) // rowh))
        self.cb_canvas.configure(height=cb_h)
        self.canvas.configure(height=chart_h)
        self.tree.configure(height=rows)
        self.bt_tree.configure(height=max(3, min(14, rows + 1)))
        root.update_idletasks()
        w = max(720, min(root.winfo_reqwidth(), self._sw - 40))
        hh = max(500, min(root.winfo_reqheight(), self._sh - 40))
        root.geometry(f"{w}x{hh}")
        return cb_h, chart_h, rows

    def _wrap_w(self):
        """提示/说明文字的折行宽度: 可用宽度减去同排按钮区, 保证整行不被裁切。"""
        return max(320, min(self._target_w - 30, self._sw - 60 - 620))

    def _col_cap(self, n_cols, hard_cap):
        """列宽上限: 让 n 列的总宽不超过窗口可用宽度, 否则横向滚动。"""
        avail = max(500, self._target_w - 160)
        return max(120, min(hard_cap, avail // max(1, n_cols)))

    def _apply_scale(self, event=None):
        """手动切换界面缩放: 字体、窗口、内部高度、列宽全部重算。"""
        base = SCALE_PRESETS.get(self.var_scale.get())
        k = self._auto_k if base is None else max(0.62, min(1.30, base))
        if abs(k - self.k) < 0.01:
            return
        self.k = k
        self.fs = set_scale(k)
        _sync_fonts()
        apply_theme(self.root, k)
        try:
            self.root.option_add("*Font", _UI_FONT)
        except tk.TclError:
            pass
        self._target_w = max(720, min(int(1660 * self.sc * k), self._sw - 60))
        self._target_h = max(520, min(int(1200 * self.sc * k), self._sh - 60))
        self.root.geometry(f"{self._target_w}x{self._target_h}")
        self.root.minsize(max(620, int(self._target_w * 0.55)),
                          max(420, int(self._target_h * 0.55)))
        self._fit_layout()
        wrap = self._wrap_w()
        for lbl in (self.lbl_hint, self.lbl_meta, self.lbl_explain,
                    self.lbl_batch_hint, self.lbl_bar_hint):
            lbl.configure(wraplength=wrap)
        hfont = tkfont.Font(font=FONT_BOLD)
        self._header_h = int(hfont.metrics("linespace")) + 13
        self.head_canvas.configure(height=self._header_h)
        self._autosize_tree(self.bt_tree, tuple(self.bt_tree["columns"]),
                            cap=self._col_cap(len(self.bt_tree["columns"]), 460))
        if self.cmp:
            cols = tuple(self.tree["columns"])
            self._autosize_tree(self.tree, cols, cap=self._col_cap(len(cols), 520))
        self._draw_header()
        self._draw_chart()
        self.status.configure(text=f"界面缩放 {k:.2f} (字号 {self.fs})")

    def _build_compare_tab(self):
        c = self.tab_cmp
        self.top_frame = top = ttk.Frame(c)
        top.pack(fill="x", padx=4, pady=(4, 2))
        # 按钮先 pack(右侧优先占位), 窗口缩小时提示文字被裁剪, 按钮始终可见
        self.btn_refresh_files = ttk.Button(top, text="刷新", width=6, command=self._refresh_files)
        self.btn_refresh_files.pack(side="right", padx=(4, 0))
        ttk.Button(top, text="全选", width=6,
                   command=self._select_all_files).pack(side="right", padx=(4, 0))
        ttk.Button(top, text="清空", width=6,
                   command=self._clear_file_selection).pack(side="right", padx=(4, 0))
        self.btn_delete_files = ttk.Button(top, text="删除选中", width=8,
                                          style="Danger.TButton", state="disabled",
                                          command=self._delete_selected_files)
        self.btn_delete_files.pack(side="right", padx=(4, 0))
        ttk.Button(top, text="打开 results 目录", width=13, style="Tool.TButton",
                   command=lambda: os.startfile(RESULTS_DIR) if os.path.isdir(RESULTS_DIR) else None
                   ).pack(side="right")
        cb_h, chart_h, tree_rows = self._adaptive_heights()
        wrap = self._wrap_w()
        self.lbl_hint = ttk.Label(top, style="Dim.TLabel", wraplength=wrap, justify="left", text="已保存结果 (results\\<模型>\\<名称>.json)。用「模型」筛选，勾选要对比的文件；"
                  "勾选后可「删除选中」(先备份到 results\\deleted\\)。双击行看明细。")
        self.lbl_hint.pack(side="left", fill="x", expand=True)

        # 二级筛选: 模型 + 日期(按结果文件的时间)
        self.filt_frame = filt = ttk.Frame(c)
        filt.pack(fill="x", padx=4, pady=(2, 0))
        ttk.Label(filt, text="模型:").pack(side="left")
        self.var_model = tk.StringVar(value="全部")
        self.cb_model = ttk.Combobox(filt, textvariable=self.var_model, width=16, state="readonly")
        self.cb_model.pack(side="left", padx=(4, 10))
        self.cb_model.bind("<<ComboboxSelected>>",
                           lambda e: (self._render_file_list(), self._rebuild_compare()))
        ttk.Label(filt, text="日期:").pack(side="left")
        self.var_date = tk.StringVar(value="全部日期")
        self.cb_date = ttk.Combobox(filt, textvariable=self.var_date, width=12, state="readonly")
        self.cb_date.pack(side="left", padx=(4, 10))
        self.cb_date.bind("<<ComboboxSelected>>",
                          lambda e: (self._render_file_list(), self._rebuild_compare()))
        self.var_count = tk.StringVar(value="")
        ttk.Label(filt, textvariable=self.var_count, style="Dim.TLabel").pack(side="left")

        # 文件勾选区(可滚动): 每个结果一个复选框, 状态存 self.file_vars, 不随焦点/切换丢失
        mid = ttk.Frame(c)
        mid.pack(fill="x", padx=4, pady=2)
        self.cb_canvas = tk.Canvas(mid, height=cb_h, background=BG_PANEL,
                                   highlightbackground=BORDER, highlightcolor=ACCENT,
                                   borderwidth=1, relief="flat")
        cbsb = ttk.Scrollbar(mid, orient="vertical", command=self.cb_canvas.yview)
        self.cb_canvas.configure(yscrollcommand=cbsb.set)
        cbsb.pack(side="right", fill="y")
        self.cb_canvas.pack(side="left", fill="both", expand=True)
        self.cb_frame = ttk.Frame(self.cb_canvas)
        self.cb_canvas.create_window((0, 0), window=self.cb_frame, anchor="nw")
        self.cb_frame.bind("<Configure>",
                          lambda e: self.cb_canvas.configure(scrollregion=self.cb_canvas.bbox("all")))

        def _cb_wheel(e):
            self.cb_canvas.yview_scroll(int(-e.delta / 120), "units")
        self.cb_canvas.bind("<MouseWheel>", _cb_wheel)
        self.cb_frame.bind("<MouseWheel>", _cb_wheel)
        self.file_vars = {}
        self._all_paths = []
        self._cb_widgets = {}
        self._color_of = {}
        self._full_name = {}
        self._label_path = {}
        self._header_h = 30
        self._tip = None
        self._tip_key = None

        st = ttk.Style(self.root)
        for i, col in enumerate(COLORS):
            st.configure(f"Series{i}.TCheckbutton", foreground=col)

        self.var_meta = tk.StringVar(value="（未加载）")
        self.lbl_meta = ttk.Label(c, textvariable=self.var_meta, style="PanelDim.TLabel",
                                  wraplength=wrap, justify="left")
        self.lbl_meta.pack(fill="x", padx=8, pady=(0, 2))

        self.ctl_frame = ctl = ttk.Frame(c)
        ctl.pack(fill="x", padx=4, pady=2)
        ttk.Label(ctl, text="基线:").pack(side="left")
        self.var_baseline = tk.StringVar()
        self.cb_baseline = ttk.Combobox(ctl, textvariable=self.var_baseline, width=12, state="readonly")
        self.cb_baseline.pack(side="left", padx=(4, 12))
        self.cb_baseline.bind("<<ComboboxSelected>>", lambda e: self._rebuild_compare())
        ttk.Label(ctl, text="指标:").pack(side="left")
        self.var_metric = tk.StringVar(value="tg t/s")
        cbm = ttk.Combobox(ctl, textvariable=self.var_metric, width=13, state="readonly",
                           values=[m for m, _ in METRIC_FIELDS])
        cbm.pack(side="left", padx=(4, 12))
        cbm.bind("<<ComboboxSelected>>", lambda e: (self._update_explain(), self._rebuild_compare()))
        ttk.Label(ctl, text="行族:").pack(side="left")
        # 默认只看 tg 行(生成阶段), 需要 pp/上下文时手动切回「全部」
        self.var_family = tk.StringVar(value="tg")
        cbf = ttk.Combobox(ctl, textvariable=self.var_family, width=8, state="readonly",
                           values=["全部", "pp", "tg", "ctx_pp", "ctx_tg"])
        cbf.pack(side="left", padx=(4, 12))
        cbf.bind("<<ComboboxSelected>>", lambda e: self._rebuild_compare())
        ttk.Label(ctl, text="图表:").pack(side="left")
        self.var_chart = tk.StringVar(value="自动")
        cbc = ttk.Combobox(ctl, textvariable=self.var_chart, width=10, state="readonly",
                           values=["自动", "折线(depth)", "分组柱状"])
        cbc.pack(side="left", padx=(4, 12))
        cbc.bind("<<ComboboxSelected>>", lambda e: self._rebuild_compare())
        ttk.Button(ctl, text="导出对比 CSV…", width=13,
                   command=self._export_csv).pack(side="right")
        # 指标含义说明(随指标下拉切换实时更新): 单独一行, 避免被控件挤掉
        self.var_explain = tk.StringVar()
        self.lbl_explain = ttk.Label(c, style="Dim.TLabel", wraplength=1080, justify="left",
                                     textvariable=self.var_explain)
        self.lbl_explain.pack(fill="x", padx=8, pady=(0, 2))
        self._update_explain()

        # 表格: ttk 表头不能按列着色, 所以表头用画布绘制 —— 每个文件列的名字
        # 用该文件在对比图里的曲线颜色, 与图表/勾选列表一一对应。
        self.tree_frame = tf = ttk.Frame(c)
        tf.pack(fill="both", expand=False, padx=4, pady=2)
        hfont = tkfont.Font(font=FONT_BOLD)
        self._header_h = int(hfont.metrics("linespace")) + 13
        self.head_canvas = tk.Canvas(tf, height=self._header_h, background=BG_HEAD,
                                     highlightthickness=0, borderwidth=0)
        self.tree = ttk.Treeview(tf, show="tree", height=tree_rows)
        self.tree.column("#0", width=0, stretch=False)
        vsb = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tf, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self.head_canvas.pack(side="top", fill="x")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", self._show_row_detail)
        self.head_canvas.bind("<Motion>", self._header_tooltip)
        self.head_canvas.bind("<Leave>", lambda e: self._hide_tip())
        self.tree.bind("<<TreeviewXView>>", lambda e: self._draw_header())
        self.tree.bind("<Configure>", lambda e: self._draw_header())

        # 图
        self.chart_frame = cf = ttk.LabelFrame(c, text=" 对比图 ")
        cf.pack(fill="both", expand=True, padx=4, pady=(2, 6))
        self.canvas = tk.Canvas(cf, height=chart_h, background=BG_PANEL,
                                highlightbackground=BORDER, highlightcolor=ACCENT,
                                borderwidth=1, relief="flat")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._draw_chart())
        # 窗口变小时表格可滚动(避免被压缩到不可见), 图表仍占剩余空间
        self.tree.bind("<MouseWheel>", lambda e: self.tree.yview_scroll(int(-e.delta / 120), "units"))

    def _update_explain(self):
        """右侧说明随指标下拉切换实时更新。"""
        self.var_explain.set(METRIC_EXPLAIN.get(
            dict(METRIC_FIELDS).get(self.var_metric.get(), ""), "Δ%=相对基线变化。"))

    def _on_tab_changed(self, event=None):
        # 切到对比页且尚未加载文件时自动加载(不覆盖已有勾选)
        if self.nb.index(self.nb.select()) == self.nb.index(self.tab_cmp):
            if not self.file_vars:
                self._refresh_files()
            # 从隐藏页切回时画布尺寸可能已变化, 重绘一次避免空白
            self._draw_chart()

    def _select_all_files(self):
        """全选当前模型筛选下的文件。"""
        for p in self._visible_paths():
            v = self.file_vars.get(p)
            if v is None:
                v = tk.BooleanVar(value=False)
                self.file_vars[p] = v
            v.set(True)
        self._update_delete_button()
        self._rebuild_compare()

    def _clear_file_selection(self):
        for v in self.file_vars.values():
            v.set(False)
        self._update_delete_button()
        self._rebuild_compare()

    def _delete_selected_files(self):
        """删除勾选的结果文件: 先复制到 results\\deleted\\ 备份, 再删除原文件。"""
        paths = [p for p, v in self.file_vars.items() if v.get() and os.path.isfile(p)]
        if not paths:
            messagebox.showinfo("删除", "没有勾选的结果文件。先勾选要删除的文件，再点「删除选中」。")
            return
        preview = "\n".join("  " + self._display_name(p) for p in paths[:12])
        if len(paths) > 12:
            preview += f"\n  … 等共 {len(paths)} 个文件"
        if not messagebox.askyesno(
                "删除结果文件",
                f"将删除 {len(paths)} 个结果文件:\n{preview}\n\n"
                "删除前会先复制到 results\\deleted\\ 作为备份(可手动恢复)。\n确认删除？"):
            return
        backup_dir = os.path.join(RESULTS_DIR, "deleted")
        try:
            os.makedirs(backup_dir, exist_ok=True)
        except OSError as e:
            messagebox.showerror("删除", f"无法创建备份目录 results\\deleted\\:\n{e}")
            return
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        moved, failed = [], []
        for src in paths:
            stem, ext = os.path.splitext(os.path.basename(src))
            dst = unique_result_path(f"{stem}_{stamp}", ext, backup_dir)
            try:
                shutil.copy2(src, dst)
                os.remove(src)
                moved.append(self._file_label(src))
            except OSError as e:
                failed.append(f"{self._file_label(src)}: {e}")
        self._refresh_files()
        self._rebuild_compare()
        if failed:
            messagebox.showerror("删除", "部分文件删除失败:\n" + "\n".join(failed))
        else:
            messagebox.showinfo("删除", f"已删除 {len(moved)} 个文件。\n备份在 results\\deleted\\")

    def _hide_tip(self):
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None
            self._tip_key = None

    def _header_tooltip(self, event):
        """鼠标移到表头(测试点那一行)时, 弹出该列对应的完整文件名。"""
        if not self.cmp:
            self._hide_tip()
            return
        if event.y > self._header_h + 2:
            self._hide_tip()
            return
        cols = list(self.tree["columns"])
        widths = [self.tree.column(c, "width") for c in cols]
        total = sum(widths)
        if total <= 0:
            return
        try:
            first, _ = self.tree.xview()
        except Exception:
            first = 0.0
        x = event.x - 1 + first * total
        idx = None
        acc = 0
        for i, w in enumerate(widths):
            if x < acc + w:
                idx = i
                break
            acc += w
        if idx is None or idx == 0:
            self._hide_tip()
            return
        j = (idx - 1) // 2
        if j >= len(self.cmp["labels"]):
            self._hide_tip()
            return
        lab = self.cmp["labels"][j]
        pth = self._label_path.get(lab)
        full = self._full_name.get(lab, lab)
        if pth:
            full += "  ·  " + self._file_date(pth)
        if self._tip is not None and self._tip_key == full:
            return
        self._hide_tip()
        w = tk.Toplevel(self.root)
        w.tk.call("wm", "override", w, 1)
        w.configure(bg=BG_HEAD)
        tk.Label(w, text=full, bg=BG_HEAD, fg=FG, font=_UI_FONT, padx=8, pady=4,
                 wraplength=max(300, self._target_w - 120), justify="left").pack()
        w.update_idletasks()
        px = self.head_canvas.winfo_rootx() + event.x - w.winfo_width() // 2
        py = self.head_canvas.winfo_rooty() + self._header_h + 6
        px = max(0, min(px, self.root.winfo_rootx() + self.root.winfo_width() - w.winfo_width()))
        w.geometry(f"+{px}+{py}")
        self._tip = w
        self._tip_key = full

    def _draw_header(self):
        """重绘画布表头: 文件列名字用该系列在图表里的颜色。"""
        cv = self.head_canvas
        cv.delete("all")
        tree = self.tree
        tw = tree.winfo_width()
        if tw < 20:
            return
        cols = list(tree["columns"])
        widths = [tree.column(c, "width") for c in cols]
        total = sum(widths)
        if total <= 0:
            return
        try:
            first, _ = tree.xview()
        except Exception:
            first = 0.0
        x = 1 - first * total
        cy = self._header_h / 2.0
        for i, col in enumerate(cols):
            w = widths[i]
            cx = x + w / 2.0
            if cx + 6 < 0 or cx - 6 > tw:      # 列完全滚出可视区, 不画
                x += w
                continue
            text = tree.heading(col, "text")
            if i == 0:
                color = FG_DIM
            elif i % 2 == 1:
                color = COLORS[((i - 1) // 2) % len(COLORS)]
            else:
                color = FG_DIM
            cv.create_text(cx, cy, text=text, fill=color, font=FONT_BOLD)
            x += w

    def _apply_series_colors(self):
        """勾选列表里的文件名颜色 = 图表里该文件曲线的颜色。"""
        for pth, cb in self._cb_widgets.items():
            i = self._color_of.get(pth)
            cb.configure(style="TCheckbutton" if i is None else f"Series{i % len(COLORS)}.TCheckbutton")

    def _model_of(self, pth):
        """文件所属模型(子目录名); 根目录文件归为「(根目录)」。"""
        parts = os.path.relpath(pth, RESULTS_DIR).split(os.sep)
        return parts[0] if len(parts) > 1 else "(根目录)"

    def _display_name(self, pth):
        """勾选列表里的显示名: 始终带模型，便于辨认。"""
        parts = os.path.relpath(pth, RESULTS_DIR).split(os.sep)
        stem = os.path.splitext(os.path.basename(pth))[0]
        return f"{parts[0]} / {stem}" if len(parts) > 1 else stem

    def _file_label(self, pth):
        """显示/列名: 同名文件跨模型时加「模型 / 」前缀，否则只用名称。"""
        lab = getattr(self, "_labels", {}).get(pth)
        if lab:
            return lab
        stem = os.path.splitext(os.path.basename(pth))[0]
        parts = os.path.relpath(pth, RESULTS_DIR).split(os.sep)
        return f"{parts[0]} / {stem}" if len(parts) > 1 else stem

    def _compute_labels(self, paths):
        from collections import Counter
        stems = Counter(os.path.splitext(os.path.basename(p))[0] for p in paths)
        self._labels = {}
        for p in paths:
            stem = os.path.splitext(os.path.basename(p))[0]
            parts = os.path.relpath(p, RESULTS_DIR).split(os.sep)
            self._labels[p] = f"{parts[0]} / {stem}" if len(parts) > 1 and stems[stem] > 1 else stem

    def _file_date(self, pth):
        """结果文件的日期(取 JSON 里的 timestamp, 取不到则用文件修改时间)。"""
        d = getattr(self, "_dates", {}).get(pth)
        if d:
            return d
        try:
            with open(pth, "r", encoding="utf-8") as f:
                head = f.read(400)
            m = re.search(r'"timestamp"\s*:\s*"(\d{4}-\d{2}-\d{2})', head)
            d = m.group(1) if m else ""
        except OSError:
            d = ""
        if not d:
            d = _dt.datetime.fromtimestamp(os.path.getmtime(pth)).strftime("%Y-%m-%d")
        self._dates[pth] = d
        return d

    def _refresh_files(self):
        self._all_paths = sorted(iter_result_files(), key=os.path.getmtime, reverse=True)
        self._compute_labels(self._all_paths)
        self._dates = {}
        models = sorted({self._model_of(p) for p in self._all_paths})
        dates = sorted({self._file_date(p) for p in self._all_paths}, reverse=True)
        self.cb_model["values"] = ["全部"] + models
        # 下拉框宽度按最长模型名实测, 避免长模型名在框内被截断显示
        self.cb_model["width"] = min(24, max(12, max((len(m) for m in models), default=4) + 2))
        self.cb_date["values"] = ["全部日期"] + dates
        if self.var_model.get() not in self.cb_model["values"]:
            self.var_model.set("全部")
        if self.var_date.get() not in self.cb_date["values"]:
            self.var_date.set("全部日期")
        self._render_file_list()

    def _visible_paths(self):
        m, d = self.var_model.get(), self.var_date.get()
        out = []
        for p in self._all_paths:
            if m != "全部" and self._model_of(p) != m:
                continue
            if d != "全部日期" and self._file_date(p) != d:
                continue
            out.append(p)
        return out

    def _render_file_list(self):
        paths = self._visible_paths()
        self._cb_widgets = {}
        for w in self.cb_frame.winfo_children():
            w.destroy()
        n_all = len(self._all_paths)
        self.var_count.set(f"共 {n_all} 个结果, 当前筛选 {len(paths)} 个")
        if not paths:
            msg = "(results\\ 下没有 json 文件)" if not self._all_paths \
                else f"(模型「{self.var_model.get()}」/ 日期「{self.var_date.get()}」下没有结果文件)"
            ttk.Label(self.cb_frame, text=msg, style="Dim.TLabel").pack(anchor="w", padx=6, pady=4)
            self._update_delete_button()
            return
        for pth in paths:
            v = self.file_vars.get(pth)
            if v is None:
                v = tk.BooleanVar(value=False)
                self.file_vars[pth] = v
            cb = ttk.Checkbutton(self.cb_frame, text=self._display_name(pth), variable=v,
                                 command=self._on_check_change)
            cb.pack(anchor="w", padx=6, pady=1)
            cb.bind("<Button-3>", lambda e, p=pth: os.startfile(p) if os.path.isfile(p) else None)
            self._cb_widgets[pth] = cb
        self._apply_series_colors()
        self.cb_canvas.update_idletasks()
        self._update_delete_button()

    def _on_check_change(self):
        self._update_delete_button()
        self._rebuild_compare()

    def _update_delete_button(self):
        """没有勾选任何(当前筛选下)文件时禁用「删除选中」，避免误点。"""
        n = sum(1 for p in self._visible_paths()
                if self.file_vars.get(p) and self.file_vars[p].get())
        try:
            self.btn_delete_files.configure(state="normal" if n else "disabled")
        except tk.TclError:
            pass

    def _selected_paths(self):
        """当前模型筛选下、且被勾选的文件。"""
        return [p for p in self._visible_paths()
                if self.file_vars.get(p) and self.file_vars[p].get() and os.path.isfile(p)]

    def _rebuild_compare(self, event=None):
        self._hide_tip()
        paths = self._selected_paths()
        if not paths:
            self.cmp = None
            self.var_baseline.set("")
            self.cb_baseline["values"] = []
            self.var_meta.set("（未加载）")
            for cid in self.tree.get_children():
                self.tree.delete(cid)
            self.tree.configure(columns=("test",))
            self.tree.heading("test", text="测试点")
            self.tree.column("test", width=240, anchor="w")
            self._draw_header()
            self._draw_chart()
            return
        reports = []
        for pth in paths:
            try:
                reports.append(load_report(pth, self._file_label(pth)))
            except (OSError, ValueError) as e:
                messagebox.showerror("对比", f"解析失败 {os.path.basename(pth)}:\n{e}")
                return
        labels = [r[0] for r in reports]
        cur = self.var_baseline.get()
        base_name = cur if cur in labels else labels[0]
        if cur != base_name:
            self.var_baseline.set(base_name)
        self.cb_baseline["values"] = labels
        labels = [base_name] + [l for l in labels if l != base_name]   # 基线排第一列
        label_of = {}
        for r, p in zip(reports, paths):
            label_of[r[0]] = p
        self._full_name = {lab: self._display_name(label_of[lab]) for lab in labels}
        self._label_path = label_of
        self._color_of = {label_of[lab]: i for i, lab in enumerate(labels)}
        self._apply_series_colors()
        field = dict(METRIC_FIELDS)[self.var_metric.get()]
        family = self.var_family.get()
        # 合并: 行按首次出现顺序
        rows_order = []
        row_map = {}
        for label, meta, rows in reports:
            for row in rows:
                if family != "全部" and row["family"] != family:
                    continue
                key = (row["name"], row["depth"], row["size"])
                if key not in row_map:
                    row_map[key] = {"label": {}}
                    rows_order.append(key)
                row_map[key]["label"][label] = row["metrics"].get(field)
        self.cmp = dict(labels=labels, field=field, metric_label=self.var_metric.get(),
                        rows=[dict(name=k[0], depth=k[1], size=k[2], label=row_map[k]["label"])
                              for k in rows_order],
                        meta={r[0]: r[1] for r in reports})
        # 元信息行
        parts = []
        for label, meta in self.cmp["meta"].items():
            ts = (meta.get("timestamp") or "")[:19]
            lat = meta.get("latency_ms")
            parts.append(f"{label}: model={meta.get('model')} {ts} 延迟={fmt_ms(lat)} "
                         f"mode={meta.get('latency_mode')}" if isinstance(lat, (int, float)) else
                         f"{label}: model={meta.get('model')} {ts}")
        self.var_meta.set("   |   ".join(parts))
        # 表格列: test + 每配置(值, Δ%)
        cols = ["test"]
        for i, lab in enumerate(labels):
            cols += [f"{lab} {self.cmp['metric_label']}" if i else f"{lab}(基线)", f"Δ{i}%" if i else "—"]
        self.tree.configure(columns=tuple(cols))
        self.tree.heading("test", text="测试点")
        self.tree.column("test", anchor="w", stretch=False)
        for i, lab in enumerate(labels):
            h = f"{lab} {self.cmp['metric_label']}" if i else f"{lab}(基线)"
            self.tree.heading(cols[1 + i * 2], text=h)
            # 列宽由字体实测决定(见 _autosize_tree), 不再估算固定值
            self.tree.column(cols[1 + i * 2], anchor="e", stretch=False)
            self.tree.heading(cols[2 + i * 2], text="(Δ%)" if i else "—")
            self.tree.column(cols[2 + i * 2], anchor="e", stretch=False)
        for cid in self.tree.get_children():
            self.tree.delete(cid)
        base = labels[0]
        for row in self.cmp["rows"]:
            vals = [row["name"]]
            tags = []
            for i, lab in enumerate(labels):
                v = row["label"].get(lab)
                if v is None:
                    vals += ["—", ""]
                elif i == 0:
                    vals += [f"{fmt_val(field, v[0])} ± {fmt_val(field, v[1])}", ""]
                else:
                    bv = row["label"].get(base)
                    if bv and bv[0] != 0:
                        d = (v[0] - bv[0]) / bv[0] * 100.0
                        vals += [f"{fmt_val(field, v[0])} ± {fmt_val(field, v[1])}", f"{d:+.1f}%"]
                        tags.append("good" if d >= 0 else "bad")
                    else:
                        vals += [f"{fmt_val(field, v[0])} ± {fmt_val(field, v[1])}", ""]
            self.tree.insert("", "end", values=vals, tags=tuple(tags))
        self.tree.tag_configure("good", foreground=GOOD)
        self.tree.tag_configure("bad", foreground=BAD)
        # 列宽全部由字体实测决定(见 _autosize_tree), 不再估算固定值
        # 列多时放宽上限: 宁可宽不可窄, 保证长表头(含 descender)不被裁切
        self._autosize_tree(self.tree, tuple(cols),
                            cap=self._col_cap(len(cols), 520))
        # 表头已用画布绘制, 这里只需保证数据行高足够(中文 descender 不被裁切)
        hstyle = ttk.Style(self.tree)
        dfont = tkfont.Font(font=_UI_FONT)
        hstyle.configure("ClipFix.Treeview",
                         rowheight=max(28, int(dfont.metrics("linespace")) + 10))
        self.tree.style = "ClipFix.Treeview"
        self._draw_header()
        self._draw_chart()

    def _show_row_detail(self, event=None):
        """双击对比表某行 → 小窗列出该测试点在各配置下的原始 mean±std。"""
        sel = self.tree.selection()
        if not sel or not self.cmp:
            return
        idx = self.tree.index(sel[0])
        if idx >= len(self.cmp["rows"]):
            return
        row = self.cmp["rows"][idx]
        w = tk.Toplevel(self.root)
        w.title(f"明细 - {row['name']}")
        w.transient(self.root)
        frm = ttk.Frame(w)
        frm.pack(fill="both", expand=True, padx=10, pady=10)
        t = ttk.Treeview(frm, columns=("cfg", "val", "std"), show="headings", height=8)
        for c, wd, an in (("cfg", 220, "w"), ("val", 90, "e"), ("std", 80, "e")):
            t.column(c, width=wd, anchor=an)
        for c, h in (("cfg", "配置"), ("val", "均值"), ("std", "标准差")):
            t.heading(c, text=h)
        for lab in self.cmp["labels"]:
            v = row["label"].get(lab)
            t.insert("", "end", values=(lab, fmt_val(self.cmp["field"], v[0]) if v else "—",
                                        fmt_val(self.cmp["field"], v[1]) if v else "—"))
        t.pack(fill="both", expand=True)
        ttk.Button(frm, text="关闭", width=10, command=w.destroy).pack(anchor="e", pady=(8, 0))
        w.update_idletasks()
        x = max(0, (w.winfo_screenwidth() - w.winfo_reqwidth()) // 2)
        y = max(0, (w.winfo_screenheight() - w.winfo_reqheight()) // 3)
        w.geometry(f"+{x}+{y}")
        style_dialog(w)

    # ---------------------------------------------------------- 图表 ----

    def _chart_series(self):
        """返回 (mode, groups, series): mode='line'|'bar'。"""
        if not self.cmp:
            return None
        rows = list(self.cmp["rows"])   # 构建时已按行族过滤，与表格一致
        field = self.cmp["field"]
        labels = self.cmp["labels"]
        depths = sorted({r["depth"] for r in rows})
        sizes = {re.match(r"(?:ctx_)?(?:pp|tg)(\d+)", r["name"]).group(1)
                 for r in rows if re.match(r"(?:ctx_)?(?:pp|tg)(\d+)", r["name"])}
        mode = self.var_chart.get()
        want_line = len(depths) > 1 and len(sizes) <= 1
        if mode == "折线(depth)":
            ok = want_line
            mode = "line" if ok else "bar"
        elif mode == "分组柱状":
            mode = "bar"
        else:
            mode = "line" if want_line else "bar"
        if mode == "line":
            series = []
            for i, lab in enumerate(labels):
                pts = [(r["depth"], r["label"][lab][0]) for r in rows
                       if lab in r["label"] and r["label"][lab] is not None]
                pts.sort()
                series.append((lab, COLORS[i % len(COLORS)], pts))
            return "line", None, series
        groups = []
        for r in rows:
            vals = [r["label"].get(lab)[0] if r["label"].get(lab) else None for lab in labels]
            groups.append((r["name"], vals))
        return "bar", groups, None

    def _draw_chart(self):
        cv = self.canvas
        cv.delete("all")
        res = self._chart_series()
        if not res:
            cv.create_text(max(cv.winfo_width(), 400) / 2, max(cv.winfo_height(), 240) / 2,
                           text="在上方选择要对比的 JSON 文件", fill=FG_DIM)
            return
        mode, groups, series = res
        field = self.cmp["field"]
        W = max(cv.winfo_width(), 400)
        H = max(cv.winfo_height(), 240)
        af = tkfont.Font(font=FONT_MONO)
        ls = af.metrics("linespace")
        L = max(40, af.measure("00.00") + 14)     # Y 轴标签实测宽度 + 呼吸空间
        R, T = 18, max(26, ls + 12)
        # 图例先按实际像素宽度布局, 再据此决定下边距 —— 右下角的文件名不再被裁切
        if mode == "line":
            legend_items = [(lab, color) for lab, color, _pts in series]
        else:
            legend_items = [(l, COLORS[i % len(COLORS)]) for i, l in enumerate(self.cmp["labels"])]
        legend_rows = self._legend_layout(legend_items, W)
        legend_h = sum(max(r[3] for r in row) + 6 for row in legend_rows) - 6
        B = max(62, legend_h + 16)       # 下边距: X 轴标签 + 图例行
        pw, ph = W - L - R, H - T - B
        grid_color, axis_fill = "#3c3c55", FG_DIM

        if mode == "line":
            allx = [p[0] for s in series for p in s[2]]
            ally = [p[1] for s in series for p in s[2]]
            if not allx or not ally:
                cv.create_text(W / 2, H / 2, text="该筛选下无数据", fill=FG_DIM)
                return
            xmin, xmax = min(allx), max(allx)
            if xmax == xmin:
                xmax += 1.0
            ymax = max(ally) * 1.15 or 1.0

            def X(x):
                return L + (x - xmin) / (xmax - xmin) * pw

            def Y(y):
                return T + (1 - y / ymax) * ph

            cv.create_line(L, T, L, H - B, fill="#6c6c88")
            cv.create_line(L, H - B, W - R, H - B, fill="#6c6c88")
            for i in range(6):
                yv = ymax * i / 5
                cv.create_line(L, Y(yv), W - R, Y(yv), fill=grid_color)
                cv.create_text(L - 6, Y(yv), text=fmt_val(field, yv), anchor="e", fill=axis_fill, font=FONT_MONO)
            # X 轴刻度去重: 数据点密集时只保留唯一深度值, 避免标签互相覆盖
            xt = sorted({p[0] for s in series for p in s[2]})
            if len(xt) > 8:
                xt = xt[::max(1, len(xt) // 8)]
            for xv in xt:
                cv.create_text(X(xv), H - B + 12, text=self._fmt_k(xv), anchor="c",
                               fill=axis_fill, font=FONT_MONO, tags="legend")
            for lab, color, pts in series:
                if not pts:
                    continue
                coords = []
                for x, y in pts:
                    coords += [X(x), Y(y)]
                if len(pts) > 1:                    # 单点系列没有线段可画
                    cv.create_line(*coords, fill=color, width=CHART_LINE_WIDTH)
                show_vals = len(pts) <= 24
                for x, y in pts:
                    cx, cy = X(x), Y(y)
                    cv.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill=color, outline="")
                    if show_vals:
                        # 数值标注: 深色底衬与背景/线条脱开, 保证可读
                        t = fmt_val(field, y)
                        wpx = len(t) * 6 + 8
                        ty = cy - 15
                        if ty - 8 < T:          # 最顶一行数值改放到点下方
                            ty = cy + 14
                        cv.create_rectangle(cx - wpx / 2, ty - 8, cx + wpx / 2, ty + 8,
                                            fill="#181825", outline="", tags="vallabel")
                        cv.create_text(cx, ty, text=t, fill=FG, font=FONT_MONO, tags="vallabel")
                # 数值标注画在最上层(底衬不会盖住其他系列的线条)
                cv.tag_raise("vallabel")
            # 指标名放到 Y 轴顶部(与轴标签错开), 底部留给图例
            cv.create_text(L, T - 12, text=self.cmp["metric_label"], anchor="w",
                           fill=axis_fill, font=(FONT[0], 10), tags="legend")
            self._legend_draw(legend_rows, W, H)
            cv.tag_raise("legend")

        else:
            if not groups:
                cv.create_text(W / 2, H / 2, text="该筛选下无数据", fill=FG_DIM)
                return
            n_lab = len(self.cmp["labels"])
            allv = [v for _g, vals in groups for v in vals if v is not None]
            ymax = (max(allv) * 1.15) if allv else 1.0
            slot = pw / len(groups)
            # X 轴名称自适应: 组够宽 → 横排长名(占满组宽); 窄 → 35° 斜排并加大下边距。
            # 不再跳号、不再固定截断 12 字符, 尽量多显示真实名称
            rotate = slot < 90
            if rotate:
                B = max(B, 104)
                ph = H - T - B

            def Y(y):
                return T + (1 - y / ymax) * ph

            cv.create_line(L, T, L, H - B, fill="#6c6c88")
            cv.create_line(L, H - B, W - R, H - B, fill="#6c6c88")
            for i in range(6):
                yv = ymax * i / 5
                cv.create_line(L, Y(yv), W - R, Y(yv), fill=grid_color)
                cv.create_text(L - 6, Y(yv), text=fmt_val(field, yv), anchor="e", fill=axis_fill, font=FONT_MONO)
            bw = max(2.0, slot * 0.45 / n_lab)      # 窄柱: 组内只占 45%, 留白更宽
            xf = tkfont.Font(font=FONT_MONO)        # X 轴名称宽度实测
            for gi, (name, vals) in enumerate(groups):
                x0 = L + slot * gi + slot * 0.275    # 柱区居中(45% 宽)
                for li, v in enumerate(vals):
                    if v is None:
                        continue
                    cv.create_rectangle(x0 + bw * li, Y(v), x0 + bw * (li + 1) - 1, H - B,
                                        fill=COLORS[li % len(COLORS)], outline="")
                    # 柱顶数值(仅在空间足够时显示, 深色底衬保证可读)
                    if bw >= 14 and Y(v) > T + 14:
                        t = fmt_val(field, v)
                        wpx = len(t) * 6 + 8
                        bx = x0 + bw * (li + 0.5)
                        # 底衬加高: 数值与图例文字行错开, 不再互相压住
                        cv.create_rectangle(bx - wpx / 2, Y(v) - 24, bx + wpx / 2, Y(v) - 4,
                                            fill="#181825", outline="", tags="vallabel")
                        cv.create_text(bx, Y(v) - 14, text=t, fill=FG, font=FONT_MONO, tags="vallabel")
                cx = L + slot * gi + slot * 0.5
                if rotate:
                    maxw = max(24, slot + 10)        # 斜排: 水平投影 = 宽度 * cos35°
                    s = name
                    while len(s) > 2 and xf.measure(s) * 0.82 > maxw:
                        s = s[:-1]
                    short = s if s == name else s + "…"
                    cv.create_text(cx, H - B + 6, text=short, anchor="e", angle=-35,
                                   fill=axis_fill, font=FONT_MONO, tags="legend")
                else:
                    maxw = max(24, slot - 6)         # 横排: 实测宽度, 不重叠也不裁切
                    s = name
                    while len(s) > 2 and xf.measure(s) > maxw:
                        s = s[:-1]
                    short = s if s == name else s + "…"
                    cv.create_text(cx, H - B + 12, text=short, anchor="c", fill=axis_fill,
                                   font=FONT_MONO, tags="legend")
            self._legend_draw(legend_rows, W, H)
            cv.create_text(L, T - 12, text=self.cmp["metric_label"], anchor="w",
                           fill=axis_fill, font=(FONT[0], 10), tags="legend")
            cv.tag_raise("vallabel")
            cv.tag_raise("legend")

    @staticmethod
    def _fmt_k(v):
        if v >= 1024 and v % 1024 == 0:
            return f"{v // 1024}K"
        return f"{v:,.0f}"

    def _legend_layout(self, items, W):
        """图例布局: 用字体实测像素宽度折行/分行, 返回 rows=[[(text,color,width,height),...],...]"""
        lf = (_UI_FONT[0], max(7, self.fs - 3))
        f = tkfont.Font(font=lf)
        ls = f.metrics("linespace")
        avail = max(140, W - 24)
        maxw = avail - 34                      # 减去色线(16)与间距(18)
        rows, row, used = [], [], 0
        for lab, color in items:
            lines, cur = [], ""
            for wd in lab.split(" "):
                if not wd:
                    continue
                trial = cur + " " + wd if cur else wd
                if f.measure(trial) <= maxw:
                    cur = trial
                else:
                    if cur:
                        lines.append(cur)
                    cur = wd
            if cur:
                lines.append(cur)
            fixed = []
            for ln in lines:
                if f.measure(ln) > maxw:       # 单个词也超宽: 硬折并加省略号
                    s = ln
                    while s and f.measure(s + "…") > maxw:
                        s = s[:-1]
                    ln = (s + "…") if s else ln[:1] + "…"
                fixed.append(ln)
            wlen = max([f.measure(l) for l in fixed] + [0]) + 34
            hgt = len(fixed) * ls
            if row and used + wlen > avail:
                rows.append(row)
                row, used = [], 0
            row.append(("\n".join(fixed), color, wlen, hgt))
            used += wlen
        if row:
            rows.append(row)
        return rows

    def _legend_draw(self, rows, W, H):
        """图例在图表最底部, 从右向左排, 每行高度实测, 不会超出画布。"""
        cv = self.canvas
        lf = (_UI_FONT[0], max(7, self.fs - 3))
        y = H - 8
        for row in reversed(rows):
            rh = max(r[3] for r in row)
            x = W - 18
            for txt, color, wlen, _h in reversed(row):
                x -= wlen
                cy = y - rh / 2.0
                cv.create_line(x, cy, x + 16, cy, fill=color, width=3, tags="legend")
                cv.create_text(x + 20, cy, text=txt, anchor="w", fill=FG,
                               font=lf, tags="legend")
                x -= 14
            y -= rh + 6

    # ---------------------------------------------------------- 预设页 ----

    def _build_batch_tab(self):
        b = self.tab_batch
        top = ttk.Frame(b)
        top.pack(fill="x", padx=4, pady=(4, 2))
        # 按钮先 pack(右侧优先占位), 窗口缩小时提示文字被裁剪, 按钮始终可见
        self.btn_preset_run = ttk.Button(top, text="▶ 运行该预设", width=14,
                                         style="Accent.TButton", command=self._run_selected_preset)
        self.btn_preset_run.pack(side="right", padx=(6, 0))
        self.btn_batch_run = ttk.Button(top, text="▶▶ 批量运行选中", width=14,
                                        style="Accent.TButton", command=self._run_all_presets)
        self.btn_batch_run.pack(side="right", padx=(6, 0))
        self.btn_batch_stop = ttk.Button(top, text="■ 停止", width=8,
                                         style="Danger.TButton", command=self.on_stop, state="disabled")
        self.btn_batch_stop.pack(side="right")
        wrap = self._wrap_w()
        self.lbl_batch_hint = ttk.Label(top, style="Dim.TLabel", wraplength=wrap, justify="left",
                                        text="单个: 选中预设 → 「▶ 运行该预设」；批量: 选中 1..N 行(Ctrl 多选) → 「▶▶ 批量运行选中」，"
                           "逐个顺序执行，自动存 results\\<名称>.json；需换服务器配置时先重启服务器再点运行(自动等端口)，"
                           "或在编辑里填前置命令自动执行。跑完去「对比」页勾选合并。")
        self.lbl_batch_hint.pack(side="left", fill="x", expand=True)

        mid = ttk.Frame(b)
        mid.pack(fill="both", expand=True, padx=4, pady=2)
        cols = ("name", "base_url", "model", "pp", "tg", "depth", "conc", "runs", "mode", "on")
        _cb_h, _chart_h, tree_rows = self._adaptive_heights()
        self.bt_tree = ttk.Treeview(mid, columns=cols, show="headings",
                                    height=max(4, min(12, tree_rows + 1)),
                                    selectmode="extended")
        for c, anc in (("name", "w"), ("base_url", "w"), ("model", "w"),
                       ("pp", "center"), ("tg", "center"), ("depth", "w"),
                       ("conc", "center"), ("runs", "center"), ("mode", "center"),
                       ("on", "center")):
            # 列宽全部由字体实测决定(见 _autosize_tree), 不再估算固定值
            self.bt_tree.column(c, anchor=anc, stretch=False)
        for c, h in (("name", "名称(结果文件名)"), ("base_url", "base-url"),
                     ("model", "模型"), ("pp", "pp"), ("tg", "tg"), ("depth", "depth"),
                     ("conc", "并发"), ("runs", "runs"), ("mode", "延迟"),
                     ("on", "启用")):
            self.bt_tree.heading(c, text=h)
        # 列宽全部由字体实测决定(见 _autosize_tree), 不再估算固定值
        self._autosize_tree(self.bt_tree, cols, cap=self._col_cap(len(cols), 460))
        # 表头行按表头字体实测加高: 列宽足够但行高不够时, 表头字符下半部仍会被裁切
        hstyle = ttk.Style(self.bt_tree)
        hfont = tkfont.Font(font=hstyle.lookup("Treeview.Heading", "font") or FONT_BOLD)
        try:
            top, bot = [int(x) for x in str(hstyle.lookup("Treeview.Heading", "padding")).split()]
        except ValueError:
            top = bot = 10
        hrow = int(hfont.metrics("linespace")) + top + bot
        hstyle.configure("ClipFix.Treeview",
                         rowheight=max(hrow, int(hstyle.lookup("Treeview", "rowheight") or 28)))
        self.bt_tree.style = "ClipFix.Treeview"
        vsb = ttk.Scrollbar(mid, orient="vertical", command=self.bt_tree.yview)
        hsb = ttk.Scrollbar(mid, orient="horizontal", command=self.bt_tree.xview)
        self.bt_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self.bt_tree.pack(side="left", fill="both", expand=True)
        self.bt_tree.tag_configure("alt", background="#2b2b3d")
        self.bt_tree.tag_configure("off", foreground="#6a6a82")
        self.bt_tree.bind("<Double-1>", lambda e: self._batch_edit_sel())
        self.bt_tree.bind("<Delete>", lambda e: self._batch_delete())

        self.bar_frame = bar = ttk.Frame(b)
        bar.pack(fill="x", padx=4, pady=(2, 6))
        for txt, cmd in (("添加预设…", lambda: self._batch_edit(None)),
                         ("编辑选中…", self._batch_edit_sel),
                         ("复制选中…", self._batch_copy_sel),
                         ("删除选中", self._batch_delete)):
            ttk.Button(bar, text=txt, width=11, style="Tool.TButton", command=cmd).pack(side="left", padx=(0, 6))
        self.lbl_bar_hint = ttk.Label(bar, style="Dim.TLabel", wraplength=wrap, justify="left",
                                      text="提示: 每个预设 = 一种服务器配置(如 MTP N)。运行前如需换配置，"
                            "先重启服务器再点运行；也可在编辑里填前置命令自动执行。双击行=编辑，Delete=删除。")
        self.lbl_bar_hint.pack(side="left", padx=8)

    def _load_batch(self):
        try:
            with open(BATCH_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and data:
                return data
        except (OSError, ValueError):
            pass
        return json.loads(json.dumps(DEFAULT_BATCH))

    def _store_batch(self):
        os.makedirs(APP_DIR, exist_ok=True)
        with open(BATCH_FILE, "w", encoding="utf-8") as f:
            json.dump(self.batch, f, ensure_ascii=False, indent=2)

    def _render_batch(self):
        for cid in self.bt_tree.get_children():
            self.bt_tree.delete(cid)
        for n, c in enumerate(self.batch):
            on = c.get("enabled", True)
            mode = {"generation": "gen", "api": "api", "none": "none"}.get(
                c.get("latency_mode", "generation"), "gen")
            vals = (c.get("name", ""), c.get("base_url", ""), c.get("model", ""),
                    c.get("pp", "") or "—", c.get("tg", "") or "—", c.get("depth", "") or "—",
                    c.get("concurrency", "") or "—", c.get("runs", "") or "—",
                    mode, "✓" if on else "—")
            tags = () if on else ("off",)
            if n % 2:
                tags = tags + ("alt",)
            self.bt_tree.insert("", "end", values=vals, tags=tags)
        # 列宽全部由字体实测决定(见 _autosize_tree), 不再估算固定值
        self._autosize_tree(self.bt_tree, ("name", "base_url", "model", "pp", "tg",
                                           "depth", "conc", "runs", "mode", "on"),
                            cap=self._col_cap(len(self.bt_tree["columns"]), 460))

    def _autosize_tree(self, tree, cols, cap=520):
        """按字体实测每列内容像素宽, 列宽取 max(表头宽, 最宽内容宽)+padding。
        ttk 列宽不足时 clam 主题会裁切字符(横向截断/下半部), 所以必须实测而不是估算。
        cap 为上限, 避免个别超长名称把整列撑得太宽。"""
        style = ttk.Style(tree)
        font = style.lookup("Treeview", "font") or FONT
        pad = 12
        f = tkfont.Font(font=font)
        # DPI 修正: f.measure() 已经按当前 tk scaling 返回物理像素, 所以实测宽度
        # 直接用; 只有 cap(设计基准, 按 100% 缩放定义)需要按 scaling 放大。
        try:
            scaling = float(self.root.tk.call('tk', 'scaling'))
        except Exception:
            scaling = 1.0
        scale = max(1.0, scaling)
        for c in cols:
            w = 0
            for cid in tree.get_children():
                w = max(w, f.measure(str(tree.set(cid, c))))
            w = max(w, f.measure(str(tree.heading(c, "text"))))
            # f.measure() 已经按当前 tk scaling 返回物理像素, 不能再二次放大
            # (旧代码 *scale 两次, 高 DPI 下列宽被撑到 1.5 倍, 窗口自然装不下)
            tree.column(c, width=min(int(cap * scale), w) + pad)

    def _batch_edit_sel(self):
        sel = self.bt_tree.selection()
        if not sel:
            messagebox.showinfo("预设", "请先选中一行")
            return
        self._batch_edit(self.bt_tree.index(sel[0]))

    def _batch_delete(self):
        sel = self.bt_tree.selection()
        if not sel:
            messagebox.showinfo("预设", "请先选中一行")
            return
        for i in sorted({self.bt_tree.index(x) for x in sel}, reverse=True):
            del self.batch[i]
        try:
            self._store_batch()
        except OSError as e:
            messagebox.showwarning("预设", f"写入失败: {e}")
        self._render_batch()

    def _batch_copy_sel(self):
        sel = self.bt_tree.selection()
        if not sel:
            messagebox.showinfo("预设", "请先选中一行")
            return
        i = self.bt_tree.index(sel[0])
        src = dict(self.batch[i])
        base = (src.get("name") or "").strip()
        nm, k = f"{base}-copy", 2
        existing = {c.get("name") for c in self.batch}
        while nm in existing:
            nm, k = f"{base}-copy{k}", k + 1
        src["name"] = nm
        self.batch.insert(i + 1, src)
        try:
            self._store_batch()
        except OSError as e:
            messagebox.showwarning("预设", f"写入失败: {e}")
        self._render_batch()
        self.bt_tree.selection_set(self.bt_tree.get_children()[i + 1])

    def _batch_edit(self, idx):
        new = idx is None
        cfg = dict(self.batch[idx]) if not new else dict(
            DEFAULT_PRESETS["单流速度"], name="新预设", pre_cmd="", post_cmd="", enabled=True)
        k = getattr(self, "k", 1.0)
        EW = max(24, int(40 * k))          # 通用输入框宽度(字符数, 随界面缩放)
        w = tk.Toplevel(self.root)
        w.title("新增预设" if new else f"编辑预设 - {cfg.get('name', '')}")
        w.transient(self.root)
        frm = ttk.Frame(w)
        frm.pack(fill="both", expand=True, padx=10, pady=8)
        strs, bools = {}, {}
        R = [0]

        def sec(title):
            ttk.Label(frm, text=title, style="Section.TLabel").grid(
                row=R[0], column=0, columnspan=4, sticky="w", pady=(10, 2))
            R[0] += 1

        def add_row(label, key, width=None, aux=None):
            r = R[0]
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", padx=(0, 8), pady=2)
            v = tk.StringVar(value=str(cfg.get(key, "") or ""))
            strs[key] = v
            e = ttk.Entry(frm, textvariable=v, width=width or EW)
            e.grid(row=r, column=1, sticky="ew", pady=2)
            e.bind("<FocusIn>", lambda ev, ent=e: ent.selection_range(0, len(ent.get())))
            if aux:
                aux(r)
            R[0] += 1

        def add_chk(r, col, label, key, default=False):
            v = tk.BooleanVar(value=bool(cfg.get(key, default)))
            bools[key] = v
            ttk.Checkbutton(frm, text=label, variable=v).grid(
                row=r, column=col * 2, sticky="w", padx=6, pady=2)

        # ------------------------------------------------ 连接与模型 ----
        sec("连接与模型")
        add_row("名称(结果文件名):", "name", 26)
        add_row("base-url:", "base_url")
        add_row("api-key(本地服务留空):", "api_key", 24)

        def _model_aux(r):
            btn_q = ttk.Button(frm, text="查询模型", width=8,
                               command=lambda: self._query_models(
                                   strs["base_url"].get(), strs["model"], btn_q))
            btn_q.grid(row=r, column=2, padx=(6, 0), pady=2)

        add_row("模型 --model:", "model", 24, aux=_model_aux)
        add_row("served-model-name(留空=同 model):", "served_model_name", 24)

        def _tok_aux(r):
            ttk.Button(frm, text="浏览…", width=7,
                       command=lambda: self._pick_tokenizer(strs["tokenizer"])).grid(
                row=r, column=2, padx=(6, 0), pady=2)

        add_row("tokenizer(本地路径或 HF 名):", "tokenizer", 24, aux=_tok_aux)

        # ------------------------------------------------ 测试矩阵 ----
        sec("测试矩阵 (depth × pp × tg × concurrency 全组合)")
        for label, key, width in (("pp (多值空格分隔):", "pp", 18),
                                  ("tg:", "tg", 18),
                                  ("depth:", "depth", 26),
                                  ("concurrency:", "concurrency", 12),
                                  ("runs (每点重复轮数):", "runs", 8),
                                  ("warmup-runs (每形状预热):", "warmup_runs", 8)):
            add_row(label, key, width)
        ttk.Label(frm, text="latency-mode:").grid(row=R[0], column=0, sticky="w", padx=(0, 8))
        v = tk.StringVar(value=str(cfg.get("latency_mode", "generation")))
        strs["latency_mode"] = v
        ttk.Combobox(frm, textvariable=v, width=12, state="readonly",
                     values=["api", "generation", "none"]).grid(row=R[0], column=1, sticky="w")
        R[0] += 1
        est = ttk.Label(frm, text="", style="Dim.TLabel")
        est.grid(row=R[0], column=0, columnspan=4, sticky="w", pady=(2, 0))
        R[0] += 1

        def update_est(*_):
            try:
                runs = int(strs["runs"].get() or 3)
                wu = int(strs["warmup_runs"].get() or 0)
            except ValueError:
                runs, wu = 0, 0
            pts = expected_points({kk: strs[kk].get()
                                   for kk in ("pp", "tg", "depth", "concurrency")})
            two = 2 if bools["prefix_caching"].get() else 1
            est.configure(text=(f"测试点 {pts} 个 × {runs} 轮 = {pts * runs * two} 次请求"
                                f"（缓存命中两阶段 ×2 已计入；另加校准与延迟探测约 {2 + 4 + wu * pts} 次）"))

        for kk in ("pp", "tg", "depth", "concurrency", "runs", "warmup_runs"):
            strs[kk].trace_add("write", update_est)

        # ------------------------------------------------ 缓存与请求控制 ----
        sec("缓存与请求控制")
        r0 = R[0]
        flags = (
            ("prefix_caching", "--enable-prefix-caching (缓存命中)"),
            ("no_cache", "--no-cache (排除缓存命中)"),
            ("exact_tg", "--exact-tg (固定输出长度, 非 vLLM 可能无效)"),
            ("skip_coherence", "--skip-coherence (跳过一致性测试)"),
            ("no_adapt_prompt", "--no-adapt-prompt (不自动调整 prompt 长度)"),
            ("exit_on_fail", "--exit-on-first-fail (测试点失败即中止)"),
            ("no_results_on_fail", "--no-results-on-fail (有失败则不写结果)"),
            ("wait_port", "运行前等待服务端口(最多约2分钟)"))
        for i, (key, label) in enumerate(flags):
            add_chk(r0 + i // 2, i % 2, label, key,
                    default=True if key == "exact_tg" else False)
        bools["prefix_caching"].trace_add("write", update_est)
        update_est()
        R[0] += (len(flags) + 1) // 2
        for note in ("--no-warmup 已移除: 它跳过的是开局的全局校准预热(2 次请求), 不是每测试点预热。",
                     "每形状预热由 warmup-runs 控制(默认 0); 只要 --adapt-prompt 开启, --no-warmup 也不生效。"):
            ttk.Label(frm, text=note, style="Dim.TLabel").grid(
                row=R[0], column=0, columnspan=4, sticky="w", pady=(1, 0))
            R[0] += 1
        add_row("前置命令(运行该预设前执行):", "pre_cmd", EW + 12)
        add_row("后置命令(每次测试后执行, 如清缓存):", "post_cmd", EW + 12)
        add_row("extra-body(额外请求字段, 逗号分隔):", "extra_body", EW + 12)

        # ------------------------------------------------ 语料与输出 ----
        sec("语料与输出")
        add_row("语料文件或 URL(留空 = data\\book.txt):", "book_url", EW)
        ttk.Label(frm, text="输出格式:").grid(row=R[0], column=0, sticky="w", padx=(0, 8))
        v = tk.StringVar(value=str(cfg.get("format", "json")))
        strs["format"] = v
        ttk.Combobox(frm, textvariable=v, width=10, state="readonly",
                     values=["json", "md", "csv"]).grid(row=R[0], column=1, sticky="w")
        R[0] += 1
        r0 = R[0]
        add_chk(r0, 0, "--save-total-throughput-timeseries", "ts_total")
        add_chk(r0, 1, "--save-all-throughput-timeseries", "ts_all")
        add_chk(r0 + 1, 0, "启用该预设(未启用则批量运行时跳过)", "enabled", default=True)
        R[0] += 2
        frm.columnconfigure(1, weight=1)

        def collect():
            out = {}
            for kk in ("name", "pre_cmd", "post_cmd", "base_url", "api_key", "model",
                       "served_model_name", "tokenizer", "pp", "tg", "depth",
                       "concurrency", "runs", "warmup_runs", "extra_body", "book_url"):
                out[kk] = strs[kk].get().strip()
            out["latency_mode"] = strs["latency_mode"].get()
            out["format"] = strs["format"].get()
            for kk, bv in bools.items():
                out[kk] = bool(bv.get())
            return out

        def preview():
            p = collect()
            p["result_name"] = p["name"] or "预设"
            cmd = "python\\python.exe " + " ".join(build_argv(p))
            messagebox.showinfo("命令预览", cmd, parent=w)

        def ok():
            p = collect()
            if not p["name"]:
                messagebox.showwarning("预设", "名称不能为空", parent=w)
                return
            if not p["base_url"].startswith(("http://", "https://")):
                messagebox.showwarning("预设", "base-url 需以 http:// 或 https:// 开头", parent=w)
                return
            bad = []
            for key in ("pp", "tg", "depth", "concurrency", "runs", "warmup_runs"):
                for val in p[key].split():
                    if not val.isdigit():
                        bad.append(f"{key}: 「{val}」 不是整数")
            if bad:
                messagebox.showwarning("预设", "参数有误:\n" + "\n".join(bad), parent=w)
                return
            if p["format"] != "json":
                messagebox.showwarning(
                    "预设", "对比页只能读取 json 结果。选 md/csv 会导出该格式，"
                    "但这份结果不会出现在对比页文件列表里。仍要保存？", parent=w)
            if new:
                self.batch.append(p)
            else:
                cur = dict(self.batch[idx])
                cur.update(p)
                self.batch[idx] = cur
            try:
                self._store_batch()
            except OSError as e:
                messagebox.showwarning("预设", f"写入失败: {e}", parent=w)
            self._render_batch()
            w.destroy()

        btns = ttk.Frame(w)
        btns.pack(fill="x", padx=10, pady=(4, 10))
        ttk.Button(btns, text="保存", width=10, style="Accent.TButton", command=ok).pack(side="right")
        ttk.Button(btns, text="取消", width=10, command=w.destroy).pack(side="right", padx=(0, 8))
        ttk.Button(btns, text="预览命令", width=11, command=preview).pack(side="left")
        # 弹窗居中(默认会出现在左上角)
        w.update_idletasks()
        x = max(0, (w.winfo_screenwidth() - w.winfo_reqwidth()) // 2)
        y = max(0, (w.winfo_screenheight() - w.winfo_reqheight()) // 3)
        w.geometry(f"+{x}+{y}")
        w.grab_set()
        style_dialog(w)

    def _pick_tokenizer(self, target_var):
        """选择本地 tokenizer.json 并填入 tokenizer 框。"""
        path = filedialog.askopenfilename(
            title="选择 tokenizer.json",
            initialdir=GREEN_DIR,
            filetypes=[("tokenizer json", "*.json"), ("所有文件", "*.*")])
        if path:
            target_var.set(path)
            self.status.configure(text=f"tokenizer: {path}")

    # ------------------------------------------------ 查询服务端模型名 ----

    def _query_models(self, base_url, target_var, btn=None):
        """GET {base-url}/models 获取在线模型名并填入 model 框(后台线程, 不卡界面)。"""
        url = (base_url or "").strip().rstrip("/")
        if not url.startswith("http"):
            messagebox.showwarning("查询模型", "请先填 base-url(如 http://127.0.0.1:8080/v1)")
            return
        urls = [url + "/models"]
        if "/v1/models" not in urls[0]:
            urls.append(url + "/v1/models")   # base-url 未带 /v1 时(vLLM 常见)再试一次
        token = f"mq{len(self._model_queries) + 1}"
        self._model_queries[token] = (target_var, btn)
        if btn is not None:
            btn.configure(state="disabled")

        def work():
            names, err = None, ""
            for u in urls:
                try:
                    import urllib.request
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    with opener.open(u, timeout=5) as r:
                        data = json.loads(r.read().decode("utf-8", "replace"))
                    names = [m.get("id") for m in data.get("data", [])
                             if isinstance(m, dict) and m.get("id")]
                    break
                except Exception as e:
                    err += f"{u}\n{e}\n"
            # 结果经队列回主线程处理(tkinter 非线程安全, 勿跨线程碰控件)
            self.q.put(("models", token, ("err", err.strip()) if names is None else ("ok", names)))

        threading.Thread(target=work, daemon=True).start()

    def _on_models_result(self, names, target_var, btn):
        if btn is not None:
            btn.configure(state="normal")
        if not names:
            messagebox.showinfo("查询模型", "未查询到模型, 服务返回的模型列表为空(GET /models)。\n请确认服务器已启动，地址与端口填写正确。")
            return
        if len(names) == 1:
            target_var.set(names[0])
            self.status.configure(text=f"已填入模型名: {names[0]}")
            return
        # 多个模型 → 居中弹窗列表选择
        w = tk.Toplevel(self.root)
        w.title("选择模型")
        w.transient(self.root)
        frm = ttk.Frame(w)
        frm.pack(fill="both", expand=True, padx=10, pady=10)
        ttk.Label(frm, text=f"服务共有 {len(names)} 个模型, 请选择:").pack(anchor="w")
        lb = tk.Listbox(frm, height=min(len(names), 12), width=48, exportselection=False)
        for n in names:
            lb.insert("end", n)
        sb = ttk.Scrollbar(frm, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        lb.selection_set(0)

        def pick():
            sel = list(lb.curselection())
            if sel:
                target_var.set(names[sel[0]])
            w.destroy()

        ttk.Button(frm, text="确定", width=10, style="Accent.TButton", command=pick).pack(pady=(8, 0), side="right")
        ttk.Button(frm, text="取消", width=10, command=w.destroy).pack(pady=(8, 0), side="right", padx=(0, 8))
        w.update_idletasks()
        x = max(0, (w.winfo_screenwidth() - w.winfo_reqwidth()) // 2)
        y = max(0, (w.winfo_screenheight() - w.winfo_reqheight()) // 3)
        w.geometry(f"+{x}+{y}")
        style_dialog(w)

    def _on_models_err(self, err, target_var, btn):
        if btn is not None:
            btn.configure(state="normal")
        messagebox.showwarning("查询模型", f"未查询到模型, 无法访问服务:\n\n{err}\n请确认服务器已启动，地址与端口填写正确。")

    def _run_selected_preset(self):
        if self.proc is not None:
            return
        sel = self.bt_tree.selection()
        if not sel:
            messagebox.showwarning("预设", "请先选中一个预设行")
            return
        cfg = dict(self.batch[self.bt_tree.index(sel[0])])
        name = re.sub(r'[\\/:*?"<>|]', "_", (cfg.get("name") or "").strip())
        if not name:
            messagebox.showwarning("预设", "该预设没有名称(结果文件名)")
            return
        cfg["result_name"] = name
        cfg.setdefault("format", "json")
        self._set_running(True)
        self.status.configure(text=f"运行预设 {name}…")
        threading.Thread(target=self._preset_run_thread, args=(cfg,), daemon=True).start()

    def _preset_run_thread(self, cfg):
        env = self._make_env()
        name = cfg["result_name"]
        pre = (cfg.get("pre_cmd") or "").strip()
        logf, logpath = self._open_run_log(name)
        ok = True
        if pre:
            logf.write(f"[preset] 前置命令: {pre}\n")
            logf.flush()
            self.q.put(("line", f"前置命令运行中(见弹出窗口): {pre[:60]}"))
            try:
                preproc = subprocess.Popen(pre, shell=True, cwd=GREEN_DIR, env=env,
                                           creationflags=subprocess.CREATE_NEW_CONSOLE)
                self.preproc = preproc    # 「停止」可终止前置命令
                rc = preproc.wait()
                self.preproc = None
                if rc != 0:
                    ok = False
                    logf.write(f"[preset] 前置命令退出码 {rc}\n")
            except OSError as e:
                ok = False
                logf.write(f"[preset] 前置命令启动失败: {e}\n")
        if ok:
            code, _ = self._run_one(cfg, env=env, log=(logf, logpath))
        else:
            code = -1
            logf.close()
        rp = cfg.get("result_path")
        saved = os.path.relpath(rp, RESULTS_DIR) if rp else f"{name}.json"
        note = ""
        if code == 0 and rp and rp.lower().endswith(".json"):
            try:
                with open(rp, "r", encoding="utf-8") as f:
                    data = json.load(f)
                got = len(data.get("benchmarks", []))
                want = expected_points(cfg) * (2 if cfg.get("prefix_caching") else 1)
                note = (f"，测到 {got} 个测试点(预期 {want})" if got < want
                        else f"，{got} 个测试点全部完成")
            except (OSError, ValueError):
                pass
        msg = f"预设 {name} 完成, 已存 results\\{saved}{note}" if code == 0 \
            else f"预设 {name} 失败(退出码 {code})"
        self.q.put(("exit", code, msg, logpath))
        return code

    def _run_all_presets(self):
        r"""批量运行选中的预设(逐个顺序执行), 每个结果自动存 results\<名称>.json"""
        if self.proc is not None or self.preproc is not None:
            messagebox.showwarning("预设", "已有任务在运行, 请先停止或等当前任务完成")
            return
        sel = self.bt_tree.selection()
        if not sel:
            messagebox.showinfo("预设", "请先选中要批量运行的预设(可按住 Ctrl 多选)")
            return
        targets, skipped = [], 0
        for cid in sel:
            i = self.bt_tree.index(cid)
            if 0 <= i < len(self.batch):
                c = dict(self.batch[i])
                if c.get("enabled", True):
                    targets.append(c)
                else:
                    skipped += 1
        if not targets:
            messagebox.showinfo("预设", "选中的预设均未启用(编辑面板里勾选「启用该预设」)")
            return
        self._set_running(True)
        self.batch_mode = True
        extra = f"，跳过 {skipped} 个未启用" if skipped else ""
        self.status.configure(text=f"批量运行选中的 {len(targets)} 个预设…{extra}")
        threading.Thread(target=self._batch_run_thread, args=(targets,), daemon=True).start()

    def _batch_run_thread(self, targets):
        env = self._make_env()
        for i, cfg in enumerate(targets):
            self._set_running(True)
            name = re.sub(r'[\\/:*?"<>|]', "_", (cfg.get("name") or "").strip())
            if not name:
                self.q.put(("bstat", f"批量 {i+1}/{len(targets)}: 预设缺少名称, 已跳过"))
                continue
            cfg["result_name"] = name
            cfg.setdefault("format", "json")
            code = self._preset_run_thread(cfg)
            if code != 0:
                self.q.put(("bstat", f"批量中止: 预设 {name} 失败(退出码 {code}), 剩余 {len(targets)-i-1} 个未运行"))
                self.batch_mode = False
                return
        self.q.put(("bstat", f"批量运行完成: 共 {len(targets)} 个预设"))
        self.batch_mode = False

    # ---------------------------------------------------------- 导出 ----

    def _export_csv(self):
        if not self.cmp:
            messagebox.showinfo("导出", "请先在上方选择要对比的 JSON 文件")
            return
        default = os.path.join(
            RESULTS_DIR, f"compare_{_dt.datetime.now():%Y%m%d_%H%M%S}.csv")
        path = filedialog.asksaveasfilename(
            parent=self.root, title="导出对比 CSV", initialfile=os.path.basename(default),
            initialdir=RESULTS_DIR if os.path.isdir(RESULTS_DIR) else APP_DIR,
            defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        labels = self.cmp["labels"]
        field = self.cmp["field"]
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["test"] + [f"{lab}.{self.cmp['metric_label']}" for lab in labels]
                           + [f"{lab}.delta_pct" for lab in labels[1:]])
                base = labels[0]
                for row in self.cmp["rows"]:
                    out = [row["name"]]
                    vals = {}
                    for lab in labels:
                        v = row["label"].get(lab)
                        vals[lab] = v
                        out.append(f"{v[0]:.4f}" if v else "")
                    for lab in labels[1:]:
                        v, bv = vals.get(lab), vals.get(base)
                        out.append(f"{(v[0] - bv[0]) / bv[0] * 100:.2f}"
                                   if v and bv and bv[0] else "")
                    w.writerow(out)
        except OSError as e:
            messagebox.showerror("导出", f"写入失败: {e}")
            return
        self.status.configure(text=f"已导出: {path}")


def main():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    # 关键: 开启 DPI awareness 后 Tk 仍按 96dpi 计算 measure(), 但字形按系统
    # 缩放(125%/150%)渲染 —— 必须把 tk scaling 设为真实 DPI, 实测宽度才与屏幕一致。
    try:
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGICALPIXELS
        ctypes.windll.user32.ReleaseDC(0, hdc)
        if dpi and dpi > 96:
            root.tk.call('tk', 'scaling', dpi / 96.0)
    except Exception:
        pass
    try:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        n = migrate_legacy_results()
        if n:
            print(f"[迁移] 已把 {n} 个旧结果文件按模型名移入 results\\<模型>\\ 子目录")
    except OSError:
        pass
    BenchGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
