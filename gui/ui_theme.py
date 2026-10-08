# -*- coding: utf-8 -*-
"""Shared UI theme for the llama-benchy green portable GUI.

Dark modern palette + ttk styling helpers, imported by bench_gui.py.
Standard library only (tkinter/ttk), keeps the portable edition dependency-free.
"""
import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont

# ---------------------------------------------------------------- palette ----
BG        = "#1e1e2e"   # window background
BG_PANEL  = "#262637"   # frames / group panels
BG_FIELD  = "#2e2e42"   # entries / listbox / canvas fields
BG_HEAD   = "#313146"   # treeview header
BORDER    = "#3c3c55"
FG        = "#e6e6f0"   # main text
FG_DIM    = "#9a9ab0"   # secondary text
ACCENT    = "#7c93ff"   # primary accent (buttons, selection)
ACCENT_HL = "#9db0ff"   # hover / highlight
GOOD      = "#4ecb8b"   # positive delta
BAD       = "#ff6b6b"   # negative delta
SEL       = "#39415f"   # row selection

# 字号: 之前 9 号中文在 clam 主题下 descender(下半部)被 padding 裁切, 显示不全。
# 现在列宽按字体实测(DPI 修正), 加大字号不会再引起裁切。
# 注意: Tk 的字号是"逻辑磅", 在 150% 缩放下 11 号 ≈ 屏幕 16.5px, 视觉上已明显偏大。
# 想更大改这里即可(12/13); 改小会重新显得"太小"。
FONT_NAME  = "Microsoft YaHei UI"
BASE_FONT  = 11                      # 基准字号(对应 1650x820 逻辑分辨率)
FONT      = (FONT_NAME, BASE_FONT)
FONT_BOLD = (FONT_NAME, BASE_FONT, "bold")
FONT_TITLE = (FONT_NAME, BASE_FONT + 2, "bold")
FONT_MONO = ("Consolas", BASE_FONT - 1)

# 基准"设计画布": 11 号字 + 这套控件在 1650x820 逻辑像素下刚好完整显示
DESIGN_W, DESIGN_H = 1650.0, 820.0

CHART_COLORS = ["#8be9fd", "#50fa7b", "#bd93f9", "#ffb86c",
                "#ff79c6", "#8aff80", "#f1eb76", "#ff5555"]
CHART_LINE_WIDTH = 3   # 加粗线条/柱体, 避免与深色背景"糊"在一起


def detect_display(root):
    """返回 (dpi_scale, ui_scale, logical_w, logical_h)。

    dpi_scale: Tk 当前的 "tk scaling" —— 控件/字体实际渲染相对 100% 的倍数
               (main() 里按系统 DPI 设成 dpi/96, 所以 150% 缩放 = 1.5)。
    ui_scale : 相对基准字号的缩放系数 —— 屏幕"逻辑分辨率"越小, 字/控件越小,
               这样 1080p 下不会"显示不全", 4K 下也不会挤成一小块。
    """
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    try:
        sc = float(root.tk.call("tk", "scaling"))
    except tk.TclError:
        sc = 1.0
    sc = max(0.75, min(2.5, sc))
    lw, lh = sw / sc, sh / sc
    k = min(lw / DESIGN_W, lh / DESIGN_H)
    k = max(0.62, min(1.0, k))
    return sc, k, lw, lh


def set_scale(k):
    """按 ui_scale 重写字体常量, 返回实际字号。"""
    global FONT, FONT_BOLD, FONT_TITLE, FONT_MONO
    fs = max(8, int(round(BASE_FONT * k)))
    FONT = (FONT_NAME, fs)
    FONT_BOLD = (FONT_NAME, fs, "bold")
    FONT_TITLE = (FONT_NAME, fs + 2, "bold")
    FONT_MONO = ("Consolas", max(7, fs - 1))
    return fs


def apply_theme(root, k=1.0):
    """Enable the clam base theme and restyle every ttk widget class."""
    style = ttk.Style(root)
    style.theme_use("clam")

    try:
        linespace = tkfont.Font(font=FONT_BOLD).metrics("linespace")
    except Exception:
        linespace = 16
    pad = max(3, int(6 * k))
    btn_pad = (max(6, int(10 * k)), max(3, int(5 * k)))
    rowheight = max(24, linespace + 10)
    head_pad = (max(4, int(6 * k)), max(6, int(10 * k)))

    style.configure(".",
                    background=BG, foreground=FG, fieldbackground=BG_FIELD,
                    bordercolor=BORDER, lightcolor=BG, darkcolor=BG,
                    font=FONT, padding=pad)
    try:
        root.option_add("*Font", FONT)
        root.option_add("*TCombobox*Listbox*Background", BG_PANEL)
        root.option_add("*TCombobox*Listbox*Foreground", FG)
        root.option_add("*TCombobox*Listbox*selectBackground", ACCENT)
        root.option_add("*TCombobox*Listbox*selectForeground", "#ffffff")
    except tk.TclError:
        pass

    style.configure("TNotebook", background=BG, borderwidth=0, tabposition="n")
    # 未选中标签：更小、更暗；选中标签：更大、高亮并带描边
    style.configure("TNotebook.Tab", background="#232333", foreground=FG_DIM,
                    padding=(max(8, int(14 * k)), max(4, int(6 * k))),
                    borderwidth=0, expand=(0, 0, 0, 0))
    style.map("TNotebook.Tab",
              background=[("selected", BG_PANEL), ("active", "#2b2b3e")],
              foreground=[("selected", ACCENT_HL), ("active", FG)],
              padding=[("selected", (max(14, int(24 * k)), max(6, int(10 * k)))),
                       ("active", (max(10, int(18 * k)), max(4, int(8 * k))))],
              bordercolor=[("selected", ACCENT)],
              borderwidth=[("selected", 1)],
              expand=[("selected", (0, 0, 0, 0))])

    style.configure("TFrame", background=BG)
    style.configure("Panel.TFrame", background=BG_PANEL, borderwidth=1)
    style.configure("TLabel", background=BG, foreground=FG)
    style.configure("Panel.TLabel", background=BG_PANEL, foreground=FG)
    style.configure("Dim.TLabel", background=BG, foreground=FG_DIM)
    style.configure("PanelDim.TLabel", background=BG_PANEL, foreground=FG_DIM)
    style.configure("Accent.TLabel", background=BG, foreground=ACCENT_HL,
                    font=FONT_BOLD)
    style.configure("Section.TLabel", background=BG, foreground=ACCENT_HL,
                    font=FONT_BOLD, padding=(max(4, int(8 * k)), max(2, int(4 * k))))
    style.configure("Title.TLabel", background=BG, foreground=FG, font=FONT_TITLE)

    style.configure("TButton", background="#2f2f45", foreground=FG,
                    bordercolor=BORDER, lightcolor="#2f2f45", darkcolor="#2f2f45",
                    padding=btn_pad, relief="flat")
    style.map("TButton",
              background=[("disabled", "#26263a"), ("pressed", "#232338"),
                          ("active", "#3a3a55")],
              foreground=[("disabled", "#5c5c72")])
    style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff",
                    lightcolor=ACCENT, darkcolor=ACCENT,
                    bordercolor=ACCENT, font=FONT_BOLD,
                    padding=(max(8, int(12 * k)), max(3, int(5 * k))))
    style.map("Accent.TButton",
              background=[("disabled", "#3a4160"), ("pressed", "#5f74d8"),
                          ("active", ACCENT_HL)],
              foreground=[("disabled", "#8b93b5")])
    style.configure("Danger.TButton", background="#5a2b34", foreground="#ffd7d7",
                    lightcolor="#5a2b34", darkcolor="#5a2b34", bordercolor="#7a3b46")
    style.map("Danger.TButton",
              background=[("disabled", "#33202a"), ("pressed", "#48222b"),
                          ("active", "#6d3540")],
              foreground=[("disabled", "#7a5f66")])

    style.configure("TCheckbutton", background=BG, foreground=FG, focuscolor=BG)
    style.map("TCheckbutton", background=[("active", BG)], foreground=[("disabled", "#5c5c72")])
    style.configure("Panel.TCheckbutton", background=BG_PANEL, foreground=FG, focuscolor=BG_PANEL)

    style.configure("TEntry", fieldbackground=BG_FIELD, foreground=FG,
                    insertcolor=FG, bordercolor=BORDER, lightcolor=BORDER,
                    darkcolor=BORDER, padding=max(2, int(4 * k)), relief="flat")
    style.map("TEntry",
              fieldbackground=[("readonly", BG_PANEL)],
              bordercolor=[("focus", ACCENT)],
              lightcolor=[("focus", ACCENT)], darkcolor=[("focus", ACCENT)])

    style.configure("TCombobox", fieldbackground=BG_FIELD, background=BG_PANEL,
                    foreground=FG, arrowcolor=FG, bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER,
                    padding=max(2, int(4 * k)), relief="flat")
    style.map("TCombobox",
              fieldbackground=[("readonly", BG_PANEL)],
              selectbackground=[("readonly", BG_PANEL)],
              selectforeground=[("readonly", FG)],
              background=[("readonly", BG_PANEL), ("disabled", BG_PANEL)],
              arrowcolor=[("disabled", "#5c5c72")])

    style.configure("Treeview", background=BG_PANEL, fieldbackground=BG_PANEL,
                    foreground=FG, rowheight=rowheight, borderwidth=0, relief="flat")
    # 表头行高: clam 主题表头按 padding 计算高度, 中文 descender 需要上下留足空间
    style.configure("Treeview.Heading", background=BG_HEAD, foreground=FG_DIM,
                    font=FONT_BOLD, relief="flat", padding=head_pad)
    style.map("Treeview",
              background=[("selected", SEL)],
              foreground=[("selected", "#ffffff")])
    style.map("Treeview.Heading", background=[("active", "#3a3a52")])

    arrow = max(8, int(12 * k))
    style.configure("Vertical.TScrollbar", background="#3a3a52", troughcolor=BG_PANEL,
                    bordercolor=BG_PANEL, lightcolor="#3a3a52", darkcolor="#3a3a52",
                    arrowcolor=FG_DIM, arrowsize=arrow, relief="flat")
    style.configure("Horizontal.TScrollbar", background="#3a3a52", troughcolor=BG_PANEL,
                    bordercolor=BG_PANEL, lightcolor="#3a3a52", darkcolor="#3a3a52",
                    arrowcolor=FG_DIM, arrowsize=arrow, relief="flat")
    style.map("Vertical.TScrollbar", background=[("active", "#4a4a68")])
    style.map("Horizontal.TScrollbar", background=[("active", "#4a4a68")])

    style.configure("TProgressbar", background=ACCENT, troughcolor=BG_PANEL,
                    bordercolor=BG_PANEL, lightcolor=ACCENT, darkcolor=ACCENT,
                    thickness=max(5, int(8 * k)))

    style.configure("TLabelframe", background=BG, bordercolor=BORDER, relief="flat")
    style.configure("TLabelframe.Label", background=BG, foreground=ACCENT_HL,
                    font=FONT_BOLD)

    style.configure("Tool.TButton", padding=(max(5, int(8 * k)), max(2, int(4 * k))))
    style.configure("Status.TLabel", background="#181825", foreground=FG_DIM,
                    anchor="w", padding=(max(5, int(8 * k)), max(2, int(4 * k))))
    style.configure("Status.TProgressbar", thickness=max(5, int(8 * k)))

    root.configure(bg=BG)


def style_dialog(w):
    """Apply the dark palette to a plain tk.Toplevel dialog (entries, listbox…)."""
    w.configure(bg=BG)
    for child in w.winfo_children():
        _style_child(child)


def _style_child(w):
    try:
        cls = w.winfo_class()
    except tk.TclError:
        return
    if cls in ("Toplevel", "Frame", "Labelframe"):
        w.configure(bg=BG)
    elif cls == "Label":
        w.configure(bg=BG, fg=FG)
    elif cls in ("Entry", "Listbox"):
        w.configure(bg=BG_FIELD, fg=FG, insertbackground=FG,
                    selectbackground=ACCENT, selectforeground="#ffffff",
                    highlightbackground=BORDER, highlightcolor=ACCENT,
                    disabledbackground=BG_PANEL, disabledforeground=FG_DIM)
        if cls == "Listbox":
            w.configure(activestyle="none")
    for child in getattr(w, "winfo_children", lambda: [])():
        _style_child(child)
