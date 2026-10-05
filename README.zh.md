# llama-benchy — 离线自包含便携版（Portable Edition）

面向**任意 OpenAI 兼容端点**（llama.cpp、vLLM、SGLang 等）的 llama-bench 风格基准测试工具，
打包为 Windows x64 的**完全自包含、免安装、离线**便携包。

- **免安装** —— 便携包自带 CPython 3.12 与全部依赖。
- **不联网** —— tokenizer、语料、模型名校验全部本地化。
- **不写系统盘** —— 工具写入的一切都在自己目录内。
- 文件夹拷到任意位置，双击 `GUI.bat` 即可。

上游项目：[eugr/llama-benchy](https://github.com/eugr/llama-benchy)。
本分支**只改动离线/便携行为** —— 测试矩阵、指标与 CLI 参数与上游 `main` 完全一致。

> English version: [README.md](README.md) · 完整参数表（中文）：[docs/params.zh.md](docs/params.zh.md)
>
> 本文件是 `README.md` 的逐节对照译文，两份要同步维护。
> 不要把个人环境信息（自己的模型名、本机路径、自己机器上的跑测数据）写进任何一份文档。

---

## 为什么用这个工具

`llama-bench`（llama.cpp 自带）只能测 llama.cpp 自身，且直接调用 C++ 引擎，
所以它反映不了真实 API 客户端看到的数字。vLLM 自带的 benchmark 工具把 TTFT
统计成"第一个数据块"而不是"第一个可用 token"，而且随机 prompt 会命中前缀缓存，
使 prompt 处理速度虚高。

llama-benchy：

- 在每个**上下文深度**下分别测量 **prompt 处理速度（pp）** 和 **token 生成速度（tg）**；
- 可以测量**已缓存上下文之上**的 prompt 处理速度（前缀缓存两阶段测试）；
- 报告 `ttfr`、`est_ppt` 和端到端 `ttft`；
- 用真实 tokenizer 统计 token 数，正确处理 MTP / 投机解码的多 token 块；
- 用真实书籍文本作为 prompt 语料（比随机 token 更适合 spec-decoding / MTP 模型）。

当前只测 `/v1/chat/completions`。

---

## 快速开始

### 方式 A — 便携包（Windows x64，免安装）

1. 从 [Releases](../../releases) 下载便携 zip，解压到任意位置。
2. 启动推理服务（例如 llama.cpp 监听 `127.0.0.1:8080`）。
3. 双击 `GUI.bat`（推荐）或 `run.bat`。

便携包结构：

```
llama-benchy-portable/
├── GUI.bat                 # tkinter 控制台（推荐入口）
├── run.bat                 # 命令行方式，含默认参数
├── gui/                    # GUI 源码（tkinter，仅标准库）
├── python/                 # 内置 CPython 3.12 + site-packages（不入库）
├── llama_benchy/           # 工具源码
├── data/book.txt           # 测试语料（可换成任意长 UTF-8 文本）
├── .hf/  .tmp/  results/   # 运行时生成，只写在本目录内
```

### 方式 B — 普通 Python 安装

```bash
git clone https://github.com/<your-username>/llama-benchy-portable-win
cd llama-benchy-portable-win
pip install -r requirements.txt          # 或: pip install .
python -m llama_benchy --base-url http://127.0.0.1:8080/v1 --model qwen \
  --runs 2 --pp 512 --tg 512 --depth 512 4096 8096 --latency-mode generation
```

`run.bat` 和 `GUI.bat` 优先使用内置 `python\python.exe`，不存在时回退到系统 `python`。

---

## GUI（推荐入口）

双击 `GUI.bat` —— tkinter 控制台，两个标签页。

**预设页** —— 一个预设 = 一种服务器配置（例如 MTP3/4/5/6）：

- 内置 `mtp3`–`mtp6` 模板；可添加 / 编辑 / 复制预设，可选**前置命令**
  （在测试前执行，例如 `restart_mtp3.bat`：杀掉 llama.cpp 再以 `--mtp 3` 重启）；
- **「查询模型」**按钮读取 `{base-url}/models`，填入服务端真实模型名；
- 单个运行，或选中多个（Ctrl / 点表头）后按顺序逐个执行；
- 最多等待约 2 分钟直到服务端口就绪，然后运行并保存 `results\<名称>.json`；
- 预设列表持久化在 `gui\batch.json`。

**对比页** —— 把多份已保存的 JSON 结果合并成一张表：

- 自动加载 `results\` 下全部结果，复选框多选，基线可选；
- 显示 `均值 ± 标准差` 和 **Δ%**（绿升红降），按测试形状（pp / tg / ctx_pp / ctx_tg）对齐；
- depth 有多个值时画折线图，否则画分组柱状图；
- 合并表可导出 CSV。

**日志** —— 没有日志面板：当前阶段显示在底部状态栏，每个前置命令 / 测试弹出独立控制台窗口，
`gui\runs\<名称>_<时间>.log` 记录命令与退出码，GUI 自身崩溃写入 `gui\gui.log`。

> GUI 界面文字目前只有中文。

---

## CLI 参数

```
python -m llama_benchy --base-url URL [options]
```

完整中文参数表见 [docs/params.zh.md](docs/params.zh.md)，以下与英文版逐项一致。

### 连接与模型

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--base-url` | *（必填）* | OpenAI 兼容端点，例如 `http://127.0.0.1:8080/v1` |
| `--api-key` | `EMPTY` | API key |
| `--model` | 自动检测 | 不指定时从 `/models` 自动检测；非 HF 格式的名字（如 `my-model`）直接放行 |
| `--served-model-name` | 同 `--model` | API 请求中实际使用的模型名 |
| `--tokenizer` | 同 `--model` | HF 模型名**或本地路径**。离线兜底：内置 `assets/gpt2_tokenizer.json`。要精确 token 计数请传模型自己的 `tokenizer.json` |

### 测试矩阵

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--pp` | `[2048]` | prompt 处理 token 数（列表） |
| `--tg` | `[32]` | 生成 token 数（列表） |
| `--exact-tg` | 关 | 强制输出长度精确等于 `--tg`（`min_tokens` + `ignore_eos`），vLLM 式固定 OSL 测试；llama.cpp 不支持这两个字段 |
| `--depth` | `[0]` | 上下文深度列表（prompt 之前已有的 token 数） |
| `--runs` | `3` | 每个测试点跑几轮，报告 均值 ± 标准差 |
| `--warmup-runs` | `0` | 每个形状丢弃的预热轮数（同时也是生成延迟探测次数） |
| `--concurrency` | `[1]` | 并发级别（列表） |

组合按 **depth → pp → tg → concurrency** 的层级做笛卡尔积。

### Warmup 与延迟

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--latency-mode` | `api` | `api`（仅网络）/ `generation`（网络 + 服务端开销，推荐）/ `none` |
| `--no-warmup` | 关 | 跳过 warmup（不推荐） |
| `--skip-coherence` | 关 | 跳过 warmup 后的一致性检查 |
| `--adapt-prompt` / `--no-adapt-prompt` | 开 | 调整 prompt 长度使真实 prompt token 数贴近 `--pp` |

### 缓存与请求控制

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--enable-prefix-caching` | 关 | 两阶段测量：`ctx_pp`/`ctx_tg`（冷加载上下文）→ `pp`/`tg`（在已缓存上下文上追问）。需 `--depth > 0` |
| `--no-cache` | 关 | 加噪声避免缓存命中，并发送 `cache-prompt=false` |
| `--post-run-cmd` | — | 每次测试后执行的命令（例如清服务端缓存） |
| `--extra-body` | — | 额外 JSON 字段，`key=value` 或 `key:value`，逗号分隔 |

### 语料与输出

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--book-url` | `data/book.txt` | 本地文件路径（默认，离线）或 http(s) URL |
| `--save-result` | — | 输出文件路径；不传则不写任何文件 |
| `--format` | `md` | `md` / `json` / `csv` |
| `--save-total-throughput-timeseries` | 关 | 每秒总吞吐时间序列（仅 JSON） |
| `--save-all-throughput-timeseries` | 关 | 每请求吞吐时间序列（仅 JSON） |
| `--emit-progress PATH` | — | JSONL 进度事件流写到 PATH 或 `-`（标准输出） |

### 错误处理

| 参数 | 说明 |
|---|---|
| `--exit-on-first-fail` | 第一个测试点失败即停止 |
| `--no-results-on-fail` | 不打印 / 不保存任何结果；隐含 `--exit-on-first-fail` |

---

## 结果解读

所有时间单位为**毫秒**，数值为 `均值 ± 标准差`。

| 列 | 含义 |
|---|---|
| `t/s`（pp 行） | prompt 处理速度 = prompt token 数 ÷ `est_ppt` |
| `t/s`（tg 行） | 解码速度 = 首 token 之后的 token 数 ÷（末 token − 首 token） |
| `t/s (total)` / `t/s (req)` | 仅并发 > 1 时出现：合计吞吐 / 单请求平均吞吐 |
| `peak t/s` | 仅 tg 行：运行期间最好的 1 秒窗口 |
| `ttfr (ms)` | 首个响应分片时间（可能是空分片），含网络延迟 |
| `est_ppt (ms)` | 估算的服务端 prompt 处理耗时 = `ttfr − 实测延迟` |
| `e2e_ttft (ms)` | 首个**内容** token 时间 —— 用户实际体感延迟 |

**PP 测量口径。** 上游用首个 SSE 分片计算 `est_ppt`。在 prefill 完成前就提前发空分片的服务器
（某些投机解码服务器）会算出不可能的数值（10 万+ t/s）。本分支改用**首个真实内容 token**。
对 llama.cpp / vLLM 两个时间戳重合，数值无影响；只修正"提前发空分片"这一种情况。
已保存的 JSON 不会被追溯改变 —— 要拿正确 PP 需重新跑测试。

---

## 便携性保证

1. **离线** —— 三处可能联网的点全部本地化：模型名校验（非 HF 名放行，HF 校验失败只警告）、
   tokenizer（内置 `gpt2_tokenizer.json`）、语料（优先本地 `data/book.txt`）。
2. **不写系统盘** —— `HF_HOME` 指向 `.hf/`，缓存和临时文件都在本目录内，结果写入 `results/`，
   全程不碰 `%USERPROFILE%`。
3. **不用代理** —— `run.bat` 清空 `HTTP(S)_PROXY` 并设置干净的 `NO_PROXY`。某些环境会注入含
   `[::1]` 的 `NO_PROXY`，导致 httpx 崩溃（`InvalidURL: Invalid port ':1]'`）。
4. **`.bat` 必须保持纯 ASCII** —— cmd 按系统 ANSI 代码页读取（中文系统是 GBK），UTF-8 中文注释
   会被错位解析成命令。改 bat 时注释一律用英文。

---

## 仓库结构

```
llama-benchy-portable-win/
├── README.md / README.zh.md
├── LICENSE
├── pyproject.toml / requirements.txt
├── GUI.bat / run.bat / bootstrap.bat     # 纯 ASCII 入口
├── llama_benchy/                         # 工具源码 + assets/gpt2_tokenizer.json
├── gui/                                  # tkinter GUI（bench_gui.py, ui_theme.py）
├── docs/params.zh.md                     # 完整中文参数表
├── data/book.txt                         # 离线语料
└── tools/wait_port.py                    # run.bat 用的等端口脚本
```

运行时产物（`results/`、`.hf/`、`.tmp/`、`data/cache/`、`gui/runs/`、`gui/batch.json`、
`gui/gui.log`）和内置 `python/` 运行时都被 `.gitignore` 排除；便携包作为 Release 资产分发。

---

## 与上游的差异

| 项 | 上游 | 本版本 |
|---|---|---|
| Python 运行时 | uv / venv | 便携 zip 内置 CPython 3.12 |
| 书籍语料 | 从 Project Gutenberg 下载 | 默认读本地 `data/book.txt` |
| tokenizer | 从 HF 下载 | 内置 gpt2 兜底；支持本地路径 |
| 写入位置 | 系统缓存目录 | 只在便携包目录内 |
| PP 测量 | 首个 SSE 分片 | 首个真实内容 token（修正虚高 PP） |
| Warmup | 每形状 1 轮 | 默认 0（`--warmup-runs 1` 恢复旧行为） |
| CLI | `main` | 完全一致 |

---

## 许可证

MIT — 见 [LICENSE](LICENSE)。核心工具版权归上游
[llama-benchy](https://github.com/eugr/llama-benchy) 作者；离线/便携改动是本分支唯一新增的内容。
