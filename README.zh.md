# llama-benchy 离线绿色便携版（Portable Edition）

English version: [README.md](README.md) · 完整参数表（中文）：[docs/params.zh.md](docs/params.zh.md)

对 OpenAI 兼容端点（如 llama.cpp / vLLM）做吞吐基准测试的**完全自包含**工具。
本目录内置 Python 3.12 解释器和全部依赖，**无需安装、不访问互联网、不写 C 盘**。
整个文件夹可以拷贝到任意 Windows (x64) 机器的任意位置直接运行。

## 目录结构

```
llama-benchy-portable\
├── GUI.bat                 # ★ 推荐入口：图形界面（调参 / 预设运行 / 结果合并对比）
│                           #   GUI 自身崩溃的 traceback 会写入 gui\gui.log
├── run.bat                 # 命令行方式双击启动（参数可在 bat 里改）
├── bootstrap.bat           # 纯 clone 用户一次性装依赖（建本目录 .venv）
├── README.md / README.zh.md
├── LICENSE / pyproject.toml / requirements.txt
├── gui\bench_gui.py       # GUI 源码（tkinter 单文件，仅标准库，零外部依赖）
├── gui\batch.json         # 预设列表（预设页改动后自动生成，可删；不入库）
├── gui\runs\              # 每次运行的命令/退出码日志 <名称>_<时间>.log（自动生成）
├── tools\wait_port.py     # run.bat 用的等端口脚本（仅标准库）
├── python\                # 内置 CPython 3.12（含全部依赖，勿删；不入库，走 Release zip 分发）
│   ├── python.exe
│   └── Lib\site-packages\   # openai 之外的依赖：aiohttp/tokenizers/transformers/numpy/tabulate/pydantic/requests...
├── llama_benchy\            # 工具源码（离线改造版）
│   ├── assets\gpt2_tokenizer.json  # 内置 gpt2 tokenizer（离线兜底，无需联网下载）
│   ├── corpus.py      # 语料：本地 book.txt 优先 → data\cache → 才考虑下载
│   ├── config.py      # 配置：非 HF 模型名直接放行；HF 校验失败只警告不报错
│   └── ...            # client/runner/prompts/results/progress
├── data\
│   └── book.txt            # ★ 测试文本（可随意替换成自己的长文，UTF-8）
├── .hf\                    # HF 缓存（仅当用 HF 模型名时才可能用到；离线模式下只读不写）
├── .tmp\                   # 运行时临时目录（代替 C 盘 Temp；里面残留的空 pip-* 目录可随手删掉）
└── results/                # ★ 测试结果落盘位置（GUI 运行自动存 json，对比页从这里加载）
```

## GUI（推荐入口）

双击 `GUI.bat` 打开 tkinter 控制台（离线、零依赖；tkinter 随内置 Python 附带）。两个标签页：**预设** 和 **对比**（原「测试」页已删除，其功能由预设页承担）。

**预设页**——单个运行 / 选中批量运行（每个预设 = 一种服务器配置，如 MTP3/4/5/6）：
1. 表格内置 mtp3~mtp6 四个模板预设（单流参数）；「添加/编辑」（弹窗居中显示）可改矩阵和**前置命令（可选）**——
   在运行该预设前执行，典型用途是自动切换服务器配置（如 `restart_mtp3.bat`：杀掉 llama.cpp
   再以 `--mtp 3` 重启）。留空 = 直接对当前服务跑；「复制选中」可克隆一个预设再改参数；
    模型行旁的**「查询模型」**按钮在线访问 `{base-url}/models` 取服务端真实模型名——
    只有一个时自动填入，多个时弹窗列表选择（base-url 未带 `/v1` 会自动补上重试），
    避免不知道本地部署的模型名而填错导致测试失败
2. **单个运行**：选中一个预设 → 「▶ 运行该预设」：前置命令(如有) → 等待服务端口(最多约 2 分钟) →
   测试 → 自动存 `results\<名称>.json`；前置命令和测试都**弹出独立控制台窗口实时显示输出**（结束自动关闭）；
   进度见底部状态栏，可「■ 停止」。换配置需要重启服务器时，先手动重启再点运行即可（等端口会覆盖重启时间）；
   运行结束后有弹窗提示：成功 →「运行完成」（含结果文件名），失败 →「运行失败」（含故障日志路径）
3. **批量运行（按选中执行）**：在表格中选中 1 个或多个预设（按住 Ctrl 可多选，点表头可全选）→
   「▶▶ 批量运行选中」：按选中顺序**逐个顺序执行**，每个结果自动存 `results\<名称>.json`；
   某预设失败即中止后续（状态栏提示剩余未运行数）。未选中任何行时点「批量运行」会提示先选中预设。
   批量结束同样有弹窗提示：全部完成 →「批量运行完成」信息弹窗，某预设失败 →「批量中止」错误弹窗；
   批量过程中每个预设完成时不再单独弹窗（避免连续打扰），只在状态栏滚动显示进度
4. 跑完到**对比页**多选本轮结果合并（基线用下拉框选），直接出表 + 图
5. 预设列表持久化在 `gui\batch.json`（改动后自动生成）

**对比页**——多份结果合并对比：
1. 文件列表在**启动/切到本页时自动加载** results\ 下全部 json（「刷新」可更新，已有勾选保留）；
   **勾选复选框**多选（或点「全选」「清空」按钮），切换基线/指标不丢勾选 → 按测试形状（pp/tg/depth/concurrency）对齐成一张表：
   **基线可选**（下拉框，默认第一个选中），其余列显示 `均值±标准差` 和 **Δ%**（绿升红降）
2. 图表随指标切换：深度有多个值时自动画折线图（每配置一条线），否则分组柱状图（窄柱）；行族可筛 pp/tg/ctx_pp/ctx_tg。
   **名称显示自适应**：X 轴组名按组宽自动排布——组够宽横排占满组宽，组窄则 35° 斜排并加大下边距，不跳号、尽量多显示真实名称；
   图例中超过 26 字符的预设名在中间空格处换两行完整显示（不再截断省略）。
   **指标命名**：`pp t/s`、`pp t/s (req)`（预处理阶段）、`tg t/s`、`tg t/s (req)`（生成阶段）、`peak t/s` 等；
   控制行右侧空余处有灰色小字说明各指标含义——`(req)=每请求值=总数÷并发数`，反映单个请求的实际体验
3. 「导出对比 CSV」落盘合并表

**日志**：GUI 不显示日志面板——最新阶段在底部状态栏；每个前置命令/测试弹出独立控制台窗口实时显示
输出（结束自动关闭）；`gui\runs\<名称>_<时间>.log` 记录命令、起止时间与退出码（故障排查入口）；
GUI 进程自身崩溃见 `gui\gui.log`。

## 快速运行

**方式一**：双击 `GUI.bat`（图形界面，推荐）。

**方式二**：双击 `run.bat`（默认参数见下方）。

**方式三**：手动命令（在本目录打开 cmd）：

```bat
run.bat 里的核心命令等价于：
python\python.exe -m llama_benchy --base-url http://127.0.0.1:8080/v1 --model qwen ^
  --runs 2 --pp 512 --tg 512 --depth 512 4096 8096 --latency-mode generation
```

> `GUI.bat` / `run.bat` 和 `gui\bench_gui.py` 都会优先用内置 `python\python.exe`，
> 不存在时回退到系统 `python`（需先 `pip install -r requirements.txt`）。
> 所以没有内置解释器的纯仓库版同样可用。

常用参数：

| 参数 | 含义 |
|---|---|
| `--base-url` | 被测服务端点（OpenAI 兼容，如 llama.cpp 的 `/v1`） |
| `--model` | 服务端模型名，任意字符串均可（如 `qwen`），无需是 HF 名 |
| `--book-url` | 测试文本路径，默认 `data/book.txt`（相对本目录） |
| `--tokenizer` | 指定本地 tokenizer.json（推荐放 Qwen 自己的，token 尺寸更准） |
| `--pp / --tg` | prompt / generation token 数 |
| `--depth` | 上下文长度列表（如 `512 4096 8096`） |
| `--runs` | 每格跑几轮（全部计入数据；每形状额外预热轮由 `--warmup-runs` 控制，默认 0） |
| `--latency-mode` | `api`（默认）/ `generation`（推荐，pp 更准）/ `none`，决定延迟校准口径 |
| `--concurrency` | 并发数（默认 1） |

## 内置 python 的处理（GitHub 版）

内置运行时**不入库**，作为 Release 资产分发。实测当前运行时：11507 个文件 / 214 MB
（去掉 `__pycache__` 后 10163 个 / 192 MB），最大单文件 19.6 MB，打包后约 70 MB。

- 单文件没超 GitHub 100 MB 硬限制，理论上可入库，但不建议：1 万多个机器生成的文件
  会拖慢每次 clone，且永久留在历史里；Git LFS 免费额度（存储 + 每月流量）很容易超。
- 仓库只放源码，`python/` 已在 `.gitignore` 里；发布用
  `powershell -File tools\make_portable_zip.ps1` 生成 `llama-benchy-portable-win64.zip`
  （源码 + 运行时，自动去掉 `__pycache__`）。
- 纯 clone 用户跑一次 `bootstrap.bat`（这一步需要联网）：在本目录建 `.venv` 并装
  `requirements.txt`。

解释器查找顺序（`GUI.bat` / `run.bat` / `gui\bench_gui.py` 一致）：
`python\python.exe` → `.venv\Scripts\python.exe` → 系统 `python`。

注意：当前运行时是**完整安装版** CPython（带 `tcl\` 和 `DLLs\_tkinter.pyd`），所以 tkinter
GUI 能跑。官方 **embeddable** 包不含 tcl/tk，用 embeddable 做 bootstrap 会让 GUI 打不开；
要可下载的便携运行时请用 `python-build-standalone` 的便携构建。
确实要把运行时塞进 git 的话：`git lfs install && git lfs track "python/**"`，并把
`python/` 从 `.gitignore` 移除。

## 关键认知（给后续 AI / 维护者）

1. **离线保证**：三处原本可能联网的点已全部本地化——
   - 模型名校验：非 HF 格式的名字直接放行；HF 名查不到只警告不中断；
   - tokenizer：优先内置 `assets/gpt2_tokenizer.json`，gpt2 网络下载是最后兜底（`HF_HUB_OFFLINE=1` 下不会触发）；
   - 测试文本：默认读本地 `data/book.txt`，不存在才尝试 gutenberg 下载。
2. **bat 里的环境变量**：清空 `HTTP(S)_PROXY`、设干净的 `NO_PROXY=localhost,127.0.0.1`——
   某些环境会注入含 `[::1]` 的 NO_PROXY，导致 httpx 解析崩溃
   （报错特征：`httpx.InvalidURL: Invalid port ':1]'`）。本机测试不需要代理。
2b. **bat 文件必须保持纯 ASCII**：cmd 按系统 ANSI 代码页（中文系统是 GBK）读取 .bat，
    UTF-8 中文注释会导致字节错位、把注释碎片当命令执行（报错特征：一堆
    "xxx 不是内部或外部命令" + 乱码）。改 bat 时注释一律用英文。
3. **绿色保证**：运行时只写本目录（`.hf/`、`.tmp/`、`data/cache/`、结果文件）；
   `HF_HOME` 指向 `%~dp0.hf`，不碰 `%USERPROFILE%`。
4. **token 计数优先级**：服务端 `token_ids` > 流式 `usage` > 本地 tokenizer 估算。
   llama.cpp 不返回 token_ids 时走 usage，属正常现象；warmup 差值法会抵消
   chat template 带来的固定开销。要精确按 Qwen 分词计尺寸，传
   `--tokenizer <qwen的tokenizer.json>`。
5. **加依赖**：`python\python.exe -m pip install <包名>`（装进本目录 site-packages）。
   注意在沙箱环境里跑时先设 `TEMP/TMP=本目录\.tmp`，避免写系统 Temp 被拒。
6. **换测试文本**：直接替换 `data/book.txt`（UTF-8 纯文本即可），程序按
   tokenizer 切流取前 N 个 token，长度建议 ≥ 最大 depth×2。
7. **PP 测量口径（已修正，见 `results.py` add() 内注释）**：
    - 原逻辑 `est_ppt = ttfr - latency`，其中 ttfr 是**首个含 choices 的 SSE 分片**时间——
      哪怕只是空分片（`delta: {"role": "assistant"}`）也算。这建立在"首分片 = 首 token"的
      假设上，llama.cpp 满足该假设（prefill 完成才吐第一个分片），所以 PP 正常（百~千 t/s）。
    - **异常来源**：Strata 这类投机解码服务器会在 prefill 完成前就提前发空分片，ttfr ≈ 纯网络
      延迟（几毫秒），`est_ppt` 几乎为 0 → PP 被算成 10万~20万 t/s（明显不可能）。缓存并未复用，
      问题纯粹出在时间戳取错。
    - **修正**：`est_ppt = ttft`，即基于**首个真实内容 token**（`first_token_ts`）的时间。
      对 llama.cpp / vLLM 等正常服务器两个时间戳重合，数值零影响；只有"提前发空分片"的服务器
      会被修正为真实 prefill 速度。`ttfr` 列本身不变（仍显示首分片时间）。
    - 注意：已保存的历史 JSON 不会追溯改变，要拿正确 PP 需重新跑测试。
8. **每形状预热已默认去掉（`--warmup-runs` 默认 0）**：旧默认 1 会在每个
   depth×pp×tg×concurrency 组合前白跑一轮（相当于多运行一轮），而 `--runs` 的轮数
   本身已足够（均值±标准差）。现在 `--runs` 全部计入数据。保留的是**初始校准 warmup**
   （仅 2 次请求，用于 chat 模板 token 差值 / `--adapt-prompt` 和延迟基线），它不是每长度一遍。
   想恢复旧行为传 `--warmup-runs 1`。

## 验证记录

构建时在本机（Qwen3.8-27B-iMatrix-NVFP4-MTP @ 127.0.0.1:8080）离线跑通：
pp512@depth8096 ≈ 1180 t/s，tg512 ≈ 41–50 t/s；全程零 C 盘写入。

2026-10 对 Strata（127.0.0.1:8080, qwen38）确认：缓存未复用但 PP 虚高 10万+ t/s，
按第 7 条修正后 PP 回到千位量级，与 TTFT×测试长度反推一致（例：131K 行真实首 token
耗时约 116 s → PP ≈ 1100 t/s）。历史 JSON 不变，重新跑测试即得正确 PP。
