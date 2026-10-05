#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
llama-benchy GUI - 绿色便携版
单文件 tkinter 应用，仅用标准库（零外部依赖，离线可用）。

功能:
  * 测试页: 快速调参(全参数表单 + 预设), 一键运行 llama-benchy(子进程),
             结果自动保存到 results\<名称>.json (同名文件不覆盖: 已存在时自动改用 <名称>_2.json, <名称>_3.json …); 运行时弹出独立控制台窗口实时显示输出,
             命令/退出码记录在 gui\runs\<名称>_<时间>.log
  * 预设页: 命名预设列表(gui\batch.json), 每个预设 = 一种服务器配置(如 MTP N);
             选中 → 「运行该预设」逐个手动运行(前置命令可选, 用于自动重启/切换服务器),
             结果自动存 results\<名称>.json; 跑完到对比页多选合并对比
  * 对比页: 加载多份已保存的 JSON 结果, 按测试形状合并对比表(含相对基线的 Δ%),
             基线可选, 折线/柱状图, 导出对比 CSV

用法: GUI.bat 或 python\\python.exe gui\\bench_gui.py
"""
import csv
import datetime as _dt
import json
import os
import queue
import re
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
from ui_theme import (apply_theme, style_dialog, BG, BG_PANEL, BG_FIELD, BORDER,
                      FG, FG_DIM, ACCENT, GOOD, BAD, CHART_COLORS, CHART_LINE_WIDTH,
                      FONT as _UI_FONT, FONT_BOLD, FONT_MONO)

APP_DIR = os.path.dirname(os.path.abspath(__file__))   # gui\
GREEN_DIR = os.path.dirname(APP_DIR)                   # repo root / portable bundle root

# Interpreter priority: bundled portable runtime > local .venv (bootstrap.bat) >
# the interpreter that launched this script.
_BUNDLED_PY = os.path.join(GREEN_DIR, "python", "python.exe")
_VENV_PY = os.path.join(GREEN_DIR, ".venv", "Scripts", "python.exe")
if os.path.exists(_BUNDLED_PY):
    PYTHON_EXE = _BUNDLED_PY
elif os.path.exists(_VENV_PY):
    PYTHON_EXE = _VENV_PY
else:
    PYTHON_EXE = sys.executable

# Package source: the portable bundle keeps it under llama-benchy\, the plain repo
# layout has llama_benchy\ at the repo root. Both work.
_BUNDLED_SRC = os.path.join(GREEN_DIR, "llama-benchy")
SRC_DIR = _BUNDLED_SRC if os.path.isdir(os.path.join(_BUNDLED_SRC, "llama_benchy")) else GREEN_DIR
RESULTS_DIR = os.path.join(GREEN_DIR, "results")

BATCH_FILE = os.path.join(APP_DIR, "batch.json")
RUNS_DIR = os.path.join(APP_DIR, "runs")          # 每次运行的完整/故障日志

FONT = ("Microsoft YaHei UI", 9)
COLORS = CHART_COLORS   # 深色主题下的高对比系列色(见 ui_theme.py)

# ---------------------------------------------------------------- 预设 ----

DEFAULT_PRESETS = {
    "单流速度": dict(
        base_url="http://127.0.0.1:8080/v1", api_key="", model="qwen38",
        served_model_name="", tokenizer="",
        pp="512", tg="512", depth="512 4096 8096", concurrency="",
        runs="2", warmup_runs="",
        latency_mode="generation", prefix_caching=False, no_cache=False,
        exact_tg=False, skip_coherence=False, no_warmup=False,
        no_adapt_prompt=False, ts_total=False, ts_all=False, wait_port=True),
    "并发测试": dict(
        base_url="http://127.0.0.1:8080/v1", api_key="", model="qwen38",
        served_model_name="", tokenizer="",
        pp="512", tg="128", depth="512 4096 8096 16384", concurrency="4",
        runs="1", warmup_runs="",
        latency_mode="generation", prefix_caching=False, no_cache=False,
        exact_tg=False, skip_coherence=False, no_warmup=False,
        no_adapt_prompt=False, ts_total=False, ts_all=False, wait_port=True),
    "缓存命中": dict(
        base_url="http://127.0.0.1:8080/v1", api_key="", model="qwen38",
        served_model_name="", tokenizer="",
        pp="", tg="", depth="32768 65536", concurrency="",
        runs="3", warmup_runs="",
        latency_mode="generation", prefix_caching=True, no_cache=False,
        exact_tg=False, skip_coherence=False, no_warmup=False,
        no_adapt_prompt=False, ts_total=False, ts_all=False, wait_port=True),
}

_SINGLE_STREAM = dict(
    base_url="http://127.0.0.1:8080/v1", api_key="", model="qwen38",
    served_model_name="", tokenizer="", pp="512", tg="512", depth="512 4096 8096",
    concurrency="", runs="2", warmup_runs="", latency_mode="generation",
    prefix_caching=False, no_cache=False, exact_tg=False, skip_coherence=False,
    no_warmup=False, no_adapt_prompt=False, ts_total=False, ts_all=False, wait_port=True)
DEFAULT_BATCH = [dict(_SINGLE_STREAM, name=f"mtp{i}", pre_cmd="", enabled=True)
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


def load_report(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    label = os.path.splitext(os.path.basename(path))[0]
    return label, *parse_report_data(data)


def fmt_val(field, v):
    """按指标格式化: 毫秒类指标保留 ms(数据即毫秒, 不换算成秒), 吞吐类保留 2 位小数。"""
    if v is None:
        return "—"
    if field in _MS_FIELDS:
        return fmt_ms(v)
    return f"{v:.2f}"


# ---------------------------------------------------------------- 命令 ----

def unique_result_path(name, ext):
    """结果保存路径: 同名文件不覆盖旧文件, 依次尝试 <名称>, <名称>_2, <名称>_3 …"""
    safe = re.sub(r'[\\/:*?"<>|]', "_", name)
    path = os.path.join(RESULTS_DIR, safe + ext)
    k = 2
    while os.path.exists(path):
        path = os.path.join(RESULTS_DIR, f"{safe}_{k}{ext}")
        k += 1
    return path


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
    if p.get("ts_total"):
        a.append("--save-total-throughput-timeseries")
    if p.get("ts_all"):
        a.append("--save-all-throughput-timeseries")
    name = p.get("result_name", "").strip()
    if name:
        ext = {"json": ".json", "md": ".md", "csv": ".csv"}[p.get("format", "json")]
        path = unique_result_path(name, ext)
        p["result_path"] = path          # 实际保存路径(完成提示按此显示)
        a += ["--save-result", path,
              "--format", p.get("format", "json")]
    return a


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
        root.geometry("1140x780")
        root.minsize(1020, 640)
        apply_theme(root)
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

        sbar = ttk.Frame(root)
        sbar.pack(fill="x", side="bottom")
        self.pbar = ttk.Progressbar(sbar, mode="indeterminate", length=180)
        self.pbar.pack(side="left", padx=(8, 6))
        self.status = ttk.Label(sbar, text="就绪", style="Status.TLabel")
        self.status.pack(side="left", fill="x", expand=True)
        self.root.after(100, self._poll_queue)

        self.batch = self._load_batch()
        self._render_batch()

        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self._refresh_files()      # 启动即加载已保存的结果










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

    def _build_compare_tab(self):
        c = self.tab_cmp
        top = ttk.Frame(c)
        top.pack(fill="x", padx=4, pady=(4, 2))
        # 按钮先 pack(右侧优先占位), 窗口缩小时提示文字被裁剪, 按钮始终可见
        self.btn_refresh_files = ttk.Button(top, text="刷新", width=6, command=self._refresh_files)
        self.btn_refresh_files.pack(side="right", padx=(4, 0))
        ttk.Button(top, text="全选", width=6,
                   command=self._select_all_files).pack(side="right", padx=(4, 0))
        ttk.Button(top, text="清空", width=6,
                   command=self._clear_file_selection).pack(side="right", padx=(4, 0))
        ttk.Button(top, text="打开 results 目录", width=13, style="Tool.TButton",
                   command=lambda: os.startfile(RESULTS_DIR) if os.path.isdir(RESULTS_DIR) else None
                   ).pack(side="right")
        ttk.Label(top, style="Dim.TLabel", text="已保存的结果 (results\\*.json，自动刷新)。勾选要对比的文件；"
                             "基线用下方下拉框选择，切换基线/指标不影响勾选。双击表格行可看该测试点明细。").pack(side="left", fill="x", expand=True)

        # 文件勾选区(可滚动): 每个结果一个复选框, 状态存 self.file_vars, 不随焦点/切换丢失
        mid = ttk.Frame(c)
        mid.pack(fill="x", padx=4, pady=2)
        self.cb_canvas = tk.Canvas(mid, height=130, background=BG_PANEL,
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

        self.var_meta = tk.StringVar(value="（未加载）")
        lbl_meta = ttk.Label(c, textvariable=self.var_meta, style="PanelDim.TLabel",
                             wraplength=1080, justify="left")
        lbl_meta.pack(fill="x", padx=8, pady=(0, 2))

        ctl = ttk.Frame(c)
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
        self.var_family = tk.StringVar(value="全部")
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
        # 同一行右侧空余处: 说明各指标含义与意义(随指标下拉切换实时更新)
        self.var_explain = tk.StringVar()
        self.lbl_explain = ttk.Label(ctl, style="Dim.TLabel", wraplength=460, justify="left",
                                     textvariable=self.var_explain)
        self.lbl_explain.pack(side="right", padx=(12, 0))
        self._update_explain()

        # 表格
        tf = ttk.Frame(c)
        tf.pack(fill="both", expand=False, padx=4, pady=2)
        self.tree = ttk.Treeview(tf, show="headings", height=10)
        vsb = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tf, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", self._show_row_detail)

        # 图
        cf = ttk.LabelFrame(c, text=" 对比图 ")
        cf.pack(fill="both", expand=True, padx=4, pady=(2, 6))
        self.canvas = tk.Canvas(cf, height=340, background=BG_PANEL,
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
        for v in self.file_vars.values():
            v.set(True)
        self._rebuild_compare()

    def _clear_file_selection(self):
        for v in self.file_vars.values():
            v.set(False)
        self._rebuild_compare()

    def _refresh_files(self):
        try:
            names = [n for n in os.listdir(RESULTS_DIR) if n.lower().endswith(".json")]
        except OSError:
            return
        paths = sorted((os.path.join(RESULTS_DIR, n) for n in names),
                       key=os.path.getmtime, reverse=True)
        prev = self.file_vars          # 保留仍存在的文件的勾选状态
        for w in self.cb_frame.winfo_children():
            w.destroy()
        self.file_vars = {}
        if not paths:
            ttk.Label(self.cb_frame, text="(results\\ 下没有 json 文件)",
                      style="Dim.TLabel").pack(anchor="w", padx=6, pady=4)
            return
        for pth in paths:
            nm = os.path.basename(pth)
            v = prev.get(nm) if prev.get(nm) is not None else tk.BooleanVar(value=False)
            self.file_vars[nm] = v
            cb = ttk.Checkbutton(self.cb_frame, text=nm, variable=v,
                                 command=self._rebuild_compare)
            cb.pack(anchor="w", padx=6, pady=1)
            cb.bind("<Button-3>", lambda e, n=nm: os.startfile(os.path.join(RESULTS_DIR, n))
                    if os.path.isfile(os.path.join(RESULTS_DIR, n)) else None)
        self.cb_canvas.update_idletasks()

    def _selected_paths(self):
        out = []
        for nm, v in self.file_vars.items():
            if v.get():
                pth = os.path.join(RESULTS_DIR, nm)
                if os.path.isfile(pth):
                    out.append(pth)
        return out

    def _rebuild_compare(self, event=None):
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
            self._draw_chart()
            return
        reports = []
        for pth in paths:
            try:
                reports.append(load_report(pth))
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
                            cap=max(520, 200 + len(cols) * 15))
        # 表头行按表头字体实测加高: 列宽足够但行高不够时, 表头字符下半部仍会被裁切
        hstyle = ttk.Style(self.tree)
        hfont = tkfont.Font(font=hstyle.lookup("Treeview.Heading", "font") or FONT_BOLD)
        try:
            top, bot = [int(x) for x in str(hstyle.lookup("Treeview.Heading", "padding")).split()]
        except ValueError:
            top = bot = 10
        hrow = int(hfont.metrics("linespace")) + top + bot
        hstyle.configure("ClipFix.Treeview",
                         rowheight=max(hrow, int(hstyle.lookup("Treeview", "rowheight") or 28)))
        self.tree.style = "ClipFix.Treeview"
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
        L, R, T, B = 64, 18, 34, 62      # 下边距加大: 底部留出图例行, 与 X 轴标签分开
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
            self._legend(series, W, H)
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
            B = 62 if not rotate else 104
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
                    maxc = 22                        # 斜排可容纳更多字符(下边距已加大)
                    short = name if len(name) <= maxc else name[:maxc - 1] + "…"
                    cv.create_text(cx, H - B + 6, text=short, anchor="e", angle=-35,
                                   fill=axis_fill, font=FONT_MONO, tags="legend")
                else:
                    maxc = max(6, int(slot / 5.8))   # Consolas 8 ≈ 5.8px/字符, 横排占满组宽不重叠
                    short = name if len(name) <= maxc else name[:maxc - 1] + "…"
                    cv.create_text(cx, H - B + 12, text=short, anchor="c", fill=axis_fill,
                                   font=FONT_MONO, tags="legend")
            self._legend([(l, COLORS[i % len(COLORS)], []) for i, l in enumerate(self.cmp["labels"])], W, H)
            cv.create_text(L, T - 12, text=self.cmp["metric_label"], anchor="w",
                           fill=axis_fill, font=(FONT[0], 10), tags="legend")
            cv.tag_raise("vallabel")
            cv.tag_raise("legend")

    @staticmethod
    def _fmt_k(v):
        if v >= 1024 and v % 1024 == 0:
            return f"{v // 1024}K"
        return f"{v:,.0f}"

    def _legend(self, series, W, H):
        # 图例移到图表最底部一行(在 X 轴标签下方), 不与数据或轴标签重叠
        cv = self.canvas
        items = [(lab, color) for lab, color, _pts in series]
        # 按可容纳宽度分行(每行从右向左排, 放不下则换行)
        rows = [[]]
        for lab, color in items:
            txt = self._legend_text(lab)
            wlen = max(len(p) for p in txt.split("\n")) * 7 + 34
            if rows[-1] and sum(r[2] for r in rows[-1]) + wlen > W - 24:
                rows.append([])
            rows[-1].append((txt, color, wlen))
        y = H - 10
        for row in reversed(rows):
            x = W - 18
            for txt, color, wlen in reversed(row):
                x -= wlen
                cv.create_line(x, y, x + 16, y, fill=color, width=3, tags="legend")
                cv.create_text(x + 20, y, text=txt, anchor="w", fill=FG, font=(_UI_FONT[0], 8), tags="legend")
                x -= 14
            y -= 16

    @staticmethod
    def _legend_text(lab):
        if len(lab) <= 26:
            return lab
        mid = len(lab) // 2
        i = lab.rfind(" ", 0, mid + 8)         # 中间附近的空格处换行
        j = lab.find(" ", mid - 8)
        if i >= 0 and (j < 0 or abs(i - mid) <= abs(j - mid)):
            return f"{lab[:i].rstrip()}\n{lab[i + 1:]}"
        if j >= 0:
            return f"{lab[:j].rstrip()}\n{lab[j + 1:]}"
        return f"{lab[:mid]}…\n{lab[mid:]}"    # 无空格则硬折

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
        ttk.Label(top, style="Dim.TLabel", text="单个: 选中预设 → 「▶ 运行该预设」；批量: 选中 1..N 行(Ctrl 多选) → 「▶▶ 批量运行选中」，"
                           "逐个顺序执行，自动存 results\\<名称>.json；需换服务器配置时先重启服务器再点运行(自动等端口)，"
                           "或在编辑里填前置命令自动执行。跑完去「对比」页勾选合并。").pack(side="left", fill="x", expand=True)

        mid = ttk.Frame(b)
        mid.pack(fill="both", expand=True, padx=4, pady=2)
        cols = ("name", "base_url", "model", "pp", "tg", "depth", "conc", "runs", "mode")
        self.bt_tree = ttk.Treeview(mid, columns=cols, show="headings", height=9, selectmode="extended")
        for c, anc in (("name", "w"), ("base_url", "w"), ("model", "w"),
                       ("pp", "center"), ("tg", "center"), ("depth", "w"),
                       ("conc", "center"), ("runs", "center"), ("mode", "center")):
            # 列宽全部由字体实测决定(见 _autosize_tree), 不再估算固定值
            self.bt_tree.column(c, anchor=anc, stretch=False)
        for c, h in (("name", "名称(结果文件名)"), ("base_url", "base-url"),
                     ("model", "模型"), ("pp", "pp"), ("tg", "tg"), ("depth", "depth"),
                     ("conc", "并发"), ("runs", "runs"), ("mode", "latency")):
            self.bt_tree.heading(c, text=h)
        # 列宽全部由字体实测决定(见 _autosize_tree), 不再估算固定值
        self._autosize_tree(self.bt_tree, cols, cap=460)
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
        self.bt_tree.bind("<Double-1>", lambda e: self._batch_edit_sel())
        self.bt_tree.bind("<Delete>", lambda e: self._batch_delete())

        bar = ttk.Frame(b)
        bar.pack(fill="x", padx=4, pady=(2, 6))
        for txt, cmd in (("添加预设…", lambda: self._batch_edit(None)),
                         ("编辑选中…", self._batch_edit_sel),
                         ("复制选中…", self._batch_copy_sel),
                         ("删除选中", self._batch_delete)):
            ttk.Button(bar, text=txt, width=11, style="Tool.TButton", command=cmd).pack(side="left", padx=(0, 6))
        ttk.Label(bar, style="Dim.TLabel", text="提示: 每个预设 = 一种服务器配置(如 MTP N)。运行前如需换配置，"
                            "先重启服务器再点运行；也可在编辑里填前置命令自动执行。双击行=编辑，Delete=删除。").pack(side="left", padx=8)

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
            vals = (c.get("name", ""), c.get("base_url", ""), c.get("model", ""),
                    c.get("pp", "") or "—", c.get("tg", "") or "—", c.get("depth", "") or "—",
                    c.get("concurrency", "") or "—", c.get("runs", "") or "—",
                    c.get("latency_mode", "generation"))
            self.bt_tree.insert("", "end", values=vals,
                                tags=("alt",) if n % 2 else ())
        # 列宽全部由字体实测决定(见 _autosize_tree), 不再估算固定值
        self._autosize_tree(self.bt_tree, ("name", "base_url", "model", "pp", "tg",
                                           "depth", "conc", "runs", "mode"), cap=460)

    def _autosize_tree(self, tree, cols, cap=520):
        """按字体实测每列内容像素宽, 列宽取 max(表头宽, 最宽内容宽)+padding。
        ttk 列宽不足时 clam 主题会裁切字符(横向截断/下半部), 所以必须实测而不是估算。
        cap 为上限, 避免个别超长名称把整列撑得太宽。"""
        style = ttk.Style(tree)
        font = style.lookup("Treeview", "font") or FONT
        pad = 12
        f = tkfont.Font(font=font)
        # DPI 修正: Tk 的 measure() 按逻辑字体(96dpi)返回像素宽, 而屏幕按系统
        # 显示缩放(125%/150%)渲染, 实际字形更宽 —— 不修正就会"20字符只显示15个"。
        # Tk 的 font actual 没有 dpi, 用 tk scaling(每英寸点数)取实际渲染密度。
        try:
            dpi = float(self.root.tk.call('tk', 'scaling'))
        except Exception:
            dpi = 96.0
        scale = max(1.0, dpi / 96.0)
        for c in cols:
            w = 0
            for cid in tree.get_children():
                w = max(w, f.measure(str(tree.set(cid, c))))
            w = max(w, f.measure(str(tree.heading(c, "text"))))
            # 列宽必须"够宽"才不会被裁切; pad 给字形左右留呼吸空间
            # cap 只限"内容宽"部分, 上限本身也按 DPI 放大, 否则 cap 会反过来制造裁切
            tree.column(c, width=int(min(cap, int(w * scale)) * scale) + pad)

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
            DEFAULT_PRESETS["单流速度"], pre_cmd="", enabled=True)
        w = tk.Toplevel(self.root)
        w.title("新增预设" if new else f"编辑预设 - {cfg.get('name', '')}")
        w.transient(self.root)
        frm = ttk.Frame(w)
        frm.pack(fill="both", expand=True, padx=10, pady=10)
        strs, bools = {}, {}

        def add_row(r, label, key, width=42):
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", padx=(0, 8), pady=3)
            v = tk.StringVar(value=str(cfg.get(key, "") or ""))
            strs[key] = v
            e = ttk.Entry(frm, textvariable=v, width=width)
            e.grid(row=r, column=1, sticky="ew", pady=3)
            e.bind("<FocusIn>", lambda ev, ent=e: ent.selection_range(0, len(ent.get())))

        def add_chk(r, col, label, key):
            v = tk.BooleanVar(value=bool(cfg.get(key, False)))
            bools[key] = v
            ttk.Checkbutton(frm, text=label, variable=v).grid(row=r, column=col * 2, sticky="w", padx=6, pady=3)

        add_row(0, "名称(结果文件名):", "name", 30)
        add_row(1, "前置命令(可选, 运行该预设前执行):", "pre_cmd", 54)
        add_row(2, "base-url:", "base_url")
        # 模型行: 输入框 + 「查询模型」按钮(在线获取服务端真实模型名, 避免手填错名)
        ttk.Label(frm, text="模型 --model:").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=3)
        v = tk.StringVar(value=str(cfg.get("model", "") or ""))
        strs["model"] = v
        ent_model = ttk.Entry(frm, textvariable=v, width=30)
        ent_model.grid(row=3, column=1, sticky="ew", pady=3)
        ent_model.bind("<FocusIn>", lambda ev, e=ent_model: e.selection_range(0, len(e.get())))
        btn_q = ttk.Button(frm, text="查询模型", width=8,
                           command=lambda: self._query_models(strs["base_url"].get(), strs["model"], btn_q))
        btn_q.grid(row=3, column=2, padx=(6, 0), pady=3)
        add_row(4, "pp (多值空格分隔):", "pp", 18)
        add_row(5, "tg:", "tg", 18)
        add_row(6, "depth:", "depth", 24)
        add_row(7, "concurrency:", "concurrency", 10)
        add_row(8, "runs:", "runs", 8)
        ttk.Label(frm, text="latency-mode:").grid(row=9, column=0, sticky="w", padx=(0, 8))
        v = tk.StringVar(value=str(cfg.get("latency_mode", "generation")))
        strs["latency_mode"] = v
        ttk.Combobox(frm, textvariable=v, width=12, state="readonly",
                     values=["api", "generation", "none"]).grid(row=9, column=1, sticky="w")
        add_chk(10, 0, "--enable-prefix-caching (两阶段)", "prefix_caching")
        add_chk(10, 1, "--no-cache", "no_cache")
        add_chk(11, 0, "--exact-tg (vLLM)", "exact_tg")
        add_chk(11, 1, "--skip-coherence", "skip_coherence")
        add_chk(12, 0, "--no-warmup", "no_warmup")
        add_chk(12, 1, "运行前等待服务端口(最多约2分钟)", "wait_port")
        frm.columnconfigure(1, weight=1)

        def ok():
            nm = strs["name"].get().strip()
            if not nm:
                messagebox.showwarning("预设", "名称不能为空", parent=w)
                return
            out = {k: strs[k].get() for k in ("name", "pre_cmd", "base_url", "model",
                                              "pp", "tg", "depth", "concurrency", "runs")}
            out["latency_mode"] = strs["latency_mode"].get()
            for k, bv in bools.items():
                out[k] = bool(bv.get())
            if new:
                out.setdefault("warmup_runs", "")
                self.batch.append(out)
            else:
                cur = dict(self.batch[idx])
                cur.update(out)
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
        # 弹窗居中(默认会出现在左上角)
        w.update_idletasks()
        x = max(0, (w.winfo_screenwidth() - w.winfo_reqwidth()) // 2)
        y = max(0, (w.winfo_screenheight() - w.winfo_reqheight()) // 3)
        w.geometry(f"+{x}+{y}")
        w.grab_set()
        style_dialog(w)

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
        cfg["format"] = "json"
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
        saved = os.path.basename(cfg.get("result_path") or f"{name}.json")
        msg = f"预设 {name} 完成, 已存 results\\{saved}" if code == 0 \
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
        targets = []
        for cid in sel:
            i = self.bt_tree.index(cid)
            if 0 <= i < len(self.batch):
                targets.append(dict(self.batch[i]))
        if not targets:
            messagebox.showinfo("预设", "没有可运行的预设")
            return
        self._set_running(True)
        self.batch_mode = True
        self.status.configure(text=f"批量运行选中的 {len(targets)} 个预设…")
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
            cfg["format"] = "json"
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
    BenchGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
