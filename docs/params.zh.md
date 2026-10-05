# llama-benchy 中文参数说明

> 依据上游项目文档（https://github.com/eugr/llama-benchy）整理，并与本绿色便携版实际 `--help` 输出逐项核对一致。
> 适用版本：绿色便携版内置构建（0.0.0+local，功能与上游 main 分支 CLI 完全一致）。

---

## 一、项目简介

llama-benchy 是一个 **llama-bench 风格的基准测试工具**，用于压测任意 **OpenAI 兼容接口**（`/v1/chat/completions`）的 LLM 推理服务，如 llama.cpp、vLLM、SGLang。

它解决的核心问题：

- `llama-bench`（llama.cpp 自带）只能测 llama.cpp 自身，且直接调用 C++ 引擎，**不能代表真实 API 用户的体验**；
- vLLM 自带的 benchmark 工具难以在不同上下文长度下准确测量 prompt 处理速度（随机 prompt 会命中缓存导致 TTFT 虚低、pp 速度虚高），且其 TTFT 统计的是"第一个数据块"而非"第一个可用 token"。

llama-benchy 的特点：

- 在不同**上下文深度**下分别测量 **Prompt 处理速度（pp）** 和 **Token 生成速度（tg）**；
- 可单独测量**已有缓存上下文之上的 prompt 处理速度**（前缀缓存两阶段测试）；
- 报告 TTFR、est_ppt、端到端 TTFT 三项时间指标；
- 使用 HuggingFace tokenizer 精确统计 token 数，正确处理 MTP/投机解码的多 token 块；
- 用真实书籍文本（Project Gutenberg）作为 prompt 语料，比随机 token 更能反映 spec.decoding/MTP 模型的真实表现。

**当前限制**：只测 `/v1/chat/completions` 端点。

---

## 二、绿色便携版如何运行

本目录自包含 Python 运行时，**无需安装、无需联网、不写 C 盘**。

```bat
:: 方式一：双击现成的 bat（已含端口等待逻辑）
运行.bat                      :: 单流速度测试（pp512/tg512，depth 512/4096/8096）
便携版-缓存命中测试.bat        :: 深上下文 + 前缀缓存两阶段测试
便携版-512_16K并发速度测试-VLLM.bat   :: 并发压测（concurrency 4）

:: 方式二：手动拼参数（在"绿色便携版"目录下执行 cmd）
set PYTHONPATH=%cd%\llama-benchy
python\python.exe -m llama_benchy --base-url http://127.0.0.1:8080/v1 --model qwen38 [其他参数]
```

前提：推理服务已在本机 8080 端口就绪。三个 bat 启动前会**每 2 秒探测一次端口，最多等约 2 分钟**，超时才报错退出。

---

## 三、完整参数表

### 3.1 连接与模型

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--base-url`（必填） | — | OpenAI 兼容端点 URL，如 `http://127.0.0.1:8080/v1` |
| `--api-key` | `EMPTY` | 接口 API Key。本地服务一般不需要改 |
| `--model` | 自动检测 | 用于基准测试的模型名。不指定时尝试从端点 `/models` 接口自动检测（取第一个） |
| `--served-model-name` | 同 `--model` | 实际 API 请求中使用的模型名。当服务端注册名与 `--model` 不一致时用（如 vLLM 的 `--served-model-name`） |
| `--tokenizer` | 同 `--model` | 用于统计 token 数的 tokenizer：HF 模型名或**本地路径**。绿色便携版离线环境下非 HF 名称（如 qwen38）会自动回退到内置 gpt2 tokenizer（近似值，warmup 差值会补偿 chat 模板开销）；要精确的 Qwen token 计数请传 `--tokenizer <qwen tokenizer.json 的路径>` |

### 3.2 测试矩阵（核心参数）

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--pp` | `[2048]` | **Prompt 处理 token 数列表**（可多个，空格分隔）。每个值测一次"预填充速度"。结果行显示为 `pp<值>` |
| `--tg` | `[32]` | **Token 生成数量列表**（可多个）。每个值测一次"解码速度"。结果行显示为 `tg<值>` |
| `--exact-tg` | 关 | 强制输出长度精确等于 `--tg`：请求中附加 `min_tokens=<tg>` 和 `ignore_eos=true`。用于 vLLM 等兼容服务器的**固定 OSL 吞吐量测试**。注意 llama.cpp 不支持这两个字段，本地测别开 |
| `--depth` | `[0]` | **上下文深度列表**（可多个）：prompt 之前已有的"历史对话 token 数"。结果行显示为 `@ d<值>`。用于观察长上下文下 pp/tg 速度如何衰减 |
| `--runs` | `3` | 每个测试点的**重复次数**，报告 均值 ± 标准差 |
| `--warmup-runs` | `0` | 每个测试形状（pp×tg×depth×concurrency）**丢弃的预热运行数**。默认 0（不再每个长度额外预热一轮——它相当于白跑一轮，`--runs` 的数据已足够）；同时控制 `--latency-mode generation` 丢弃的探测次数。不影响初始 prompt 适配 warmup |
| `--concurrency` | `[1]` | **并发级别列表**（可多个，如 `1 2 4`）：每个测试点同时发出的并行请求数。用于测量负载下的吞吐扩展性、找饱和点。结果行显示为 `(c<N>)`，并额外给出 `t/s (total)` 与 `t/s (req)` 两列 |

**组合规则**：多个参数时按 **depth → pp → tg → concurrency** 的层级做全组合（笛卡尔积）。
例：`--pp 128 256 --tg 32 64 --depth 0 1024` 会测 2×2×2 = 8 个测试点，每点再跑 `--runs` 次。

### 3.3 Warmup 与延迟测量

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--latency-mode` | `api` | 延迟测量方法（用于从 ttfr 中扣除网络/服务开销，算出 est_ppt）：<br>• `api`：调一次 `/models` 接口计时，只扣掉**网络延迟**；<br>• `generation`：**生成 1 个 token** 计时，尽量扣掉网络 + 服务端开销，pp 速度更接近真实值（短 prompt 时尤其推荐）；默认发 4 次单 token 流式探测，丢弃第 1 次，平均后 3 次（次数由 `--warmup-runs` 控制）；<br>• `none`：延迟按 0 处理 |
| `--no-warmup` | 关 | 跳过 warmup 阶段（不推荐：warmup 用于校准 prompt 实际 token 数和延迟基线） |
| `--skip-coherence` | 关 | 跳过 warmup 后的**一致性测试**（程序会问模型"法国首都叫什么"，答不出 Paris 就报错退出，防止对着错误/未加载完的服务白测） |
| `--adapt-prompt` / `--no-adapt-prompt` | 开 / 关 | 默认开启：根据 warmup 时服务端实际消耗的 token 数与请求文本的差值（chat 模板开销等），**自动调整 prompt 文本长度**，使真实 prompt token 数贴近 `--pp` 指定值。`--no-adapt-prompt` 关闭该行为 |

### 3.4 缓存与请求控制

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--enable-prefix-caching` | 关 | 启用**前缀缓存性能测量**（需 `--depth > 0`）。每个测试点改跑两步：<br>① **上下文加载**：把 depth 个 token 作为 system 消息 + 最小 user 探测消息发出，强制服务端处理并缓存该上下文 → 报告为 `ctx_pp @ d<值>` / `ctx_tg @ d<值>`；<br>② **推理**：同一上下文（system）+ 真正的 prompt（user），服务端应复用缓存 → 报告为标准 `pp<值> @ d<值>` / `tg<值> @ d<值>`。<br>此时 pp/tg 显示的是"上下文已预热后，追问 prompt 的真实处理/生成速度" |
| `--no-cache` | 关 | 给请求加随机噪声以**避免前缀缓存命中**，同时向服务端发送 `cache-prompt=false`。一般不必开（相同文本重复跑时命中概率本来就低）；若结果异常偏高怀疑命中缓存时用它排查 |
| `--post-run-cmd` | — | 每次测试运行后执行的命令（如清服务器缓存）。例：`--post-run-cmd "curl -X POST http://127.0.0.1:8080/v1/cache/clear"` |
| `--extra-body` | — | 合并进基准请求 JSON body 的**额外字段**。支持 `key=value` 或 `key:value`，逗号分隔或重复传参。例：`--extra-body min_tokens=1024,ignore_eos=true`（固定输出长度场景优先用 `--exact-tg`） |

### 3.5 文本语料

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--book-url` | **本地文件**（绿色版：`data\book.txt`） | prompt 语料来源。上游默认从 Project Gutenberg 下载《福尔摩斯》；绿色便携版已离线化：**默认读目录内 `data\book.txt`**，也可传 http(s) URL（需联网）。要换测试文本直接编辑 `data\book.txt` 即可 |

### 3.6 结果输出

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--save-result` | 无（只打印到终端） | 结果保存到的**文件路径**。绿色版不带此参数时不写任何文件 |
| `--format` | `md` | 输出格式：`md`（Markdown 表格，人读最方便）/ `json`（信息最全，含逐 run 明细，适合二次分析画图）/ `csv` |
| `--save-total-throughput-timeseries` | 关 | 保存**总吞吐**的时间序列（峰值计算中每个 1 秒窗口的数值），仅 JSON 输出时有效 |
| `--save-all-throughput-timeseries` | 关 | 保存**每个单独请求**的吞吐时间序列，仅 JSON 输出时有效 |
| `--emit-progress PATH` | 无 | 运行期间向 PATH（或 `-` 表示标准输出）持续写 **JSONL 进度事件流**，供外部可视化器消费（实时 TUI、Web 仪表盘、事后分析）。服务端返回 `token_ids` 时每块 token 数精确；否则 `tokens` 事件标记 `estimated: true`，以 `request_end.total_tokens` 为权威总数 |

### 3.7 错误处理

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--exit-on-first-fail` | 关 | 第一个测试点失败即停止并返回非零退出码（默认行为是跳过失败的点继续测完） |
| `--no-results-on-fail` | 关 | 出错时**不打印/不保存任何结果**，并自动隐含开启 `--exit-on-first-fail` |

### 3.8 其他

| 参数 | 说明 |
|---|---|
| `-h, --help` | 显示帮助 |
| `--version` | 显示版本号（绿色版为 `0.0.0+local`） |

---

## 四、输出指标说明

结果表所有时间单位为**毫秒（ms）**，数值均为 `均值 ± 标准差`。

### 4.1 延迟校准（先理解它才能看懂 est_ppt）

程序按 `--latency-mode` 实测一个"固定开销"，然后：

```
est_ppt = ttfr - 实测延迟
```

- `api` 模式：只扣网络延迟；
- `generation` 模式：扣网络 + 服务端调度开销（推荐，pp 速度更接近真实值）；
- `none` 模式：不扣。

### 4.2 各列含义

| 列 | 含义与算法 |
|---|---|
| `t/s`（pp 行） | **预填充速度** = prompt token 总数 ÷ est_ppt |
| `t/s`（tg 行） | **解码速度** = 首 token 之后观察到的 token 数 ÷ (末 token 时刻 − 首 token 时刻)。块流式后端中随首个内容时间戳一起到达的 token 不计入（无可见生成间隔）；若整个响应只有一个含内容的块，该列留空 |
| `t/s (total)` / `t/s (req)` | 仅并发 > 1 时出现：**所有并发请求的合计吞吐** / **单请求平均吞吐**。用 total 找服务器饱和点（加客户端不再涨 total 的位置） |
| `peak t/s` | 仅 tg 行：**运行期间任意 1 秒窗口内观察到的最高生成吞吐**（含 MTP 多 token 块的爆发值） |
| `ttfr (ms)` | **Time To First Response** = 首个响应数据块时刻 − 请求发出时刻。收到的是"任意流数据"（可能是不含 token 的空块/role 块，不含 HTTP 头），**包含网络延迟**。vLLM 官方 bench 的 TTFT 也是同样口径 |
| `est_ppt (ms)` | **估算的服务端 prompt 处理耗时** = ttfr − 实测延迟。pp 速度用它计算 |
| `e2e_ttft (ms)` | **端到端首 token 时间** = 首个内容 token 时刻 − 请求发出时刻。用户实际"看到第一个字"的体感延迟 |

### 4.3 前缀缓存两阶段（`--enable-prefix-caching`）的结果行

```
ctx_pp @ d32768   ← 冷加载：把 32K 上下文整段喂给服务器的处理速度（无缓存）
ctx_tg @ d32768   ← 加载时的生成速度
pp2048 @ d32768   ← 热追问：上下文已缓存，只处理新 prompt（2048 token）的速度
tg32 @ d32768     ← 热追问下的生成速度
```

对比 `ctx_pp` 与 `pp<值>` 即可看出前缀缓存带来的加速比。

### 4.4 并发测试结果行

```
pp2048 (c1)   t/s(total)=7803  t/s(req)=7803     ← 单请求基线
pp2048 (c2)   t/s(total)=7198  t/s(req)=4872     ← 2 并发：total 下降说明该负载下已劣化
tg32  (c2)    t/s(total)=111.3 t/s(req)=56.2     ← 合计解码吞吐 vs 单请求
```

注意：当前实现中同一测试点的 N 个请求**同时发出**；开 `--enable-prefix-caching` 时，N 个 prefill（上下文加载）也同时执行，随后才是并发追问。

---

## 五、实用建议（上游文档推荐）

1. **测 pp 速度用 `--latency-mode generation`**，尤其短 prompt 时结果更接近真实值；
2. 一般**不需要**在服务器上关缓存（相同文本重复跑命中概率低）；若怀疑命中导致数值虚高，加 `--no-cache` 排查；
3. **固定输出长度的吞吐测试**（vLLM）优先用 `--exact-tg`，不要手动拼 `min_tokens`/`ignore_eos`；
4. 需要进一步分析或画图时导出 **JSON**（信息最全），配合 `--save-total-throughput-timeseries` / `--save-all-throughput-timeseries`；
5. 多参数组合是笛卡尔积，注意总测试时长 = depth×pp×tg×concurrency×(runs+warmup-runs) 次请求。

---

## 六、绿色便携版与上游的差异（仅离线化，不改测试架构）

| 项 | 上游 | 绿色便携版 |
|---|---|---|
| Python 运行时 | uv / venv 安装 | 目录内置完整 CPython 3.12 + 依赖，自包含 |
| 书籍语料 | 联网下载 Gutenberg《福尔摩斯》 | **默认读本地 `data\book.txt`**（可编辑）；传 URL 才联网 |
| tokenizer | HF 名称走网络下载 | 非 HF 名称（如 qwen38）**离线回退到内置 gpt2 tokenizer**（近似计数 + warmup 差值补偿）；要精确 Qwen 计数用 `--tokenizer <本地路径>` |
| 结果文件 | 同左 | 不带 `--save-result` 时只打印到终端，**不写任何文件** |
| 环境变量 | — | bat 内已隔离：禁代理、`HF_HUB_OFFLINE=1`、`HF_HOME` 指向目录内 `.hf`，全程不写 C 盘 |
| CLI 参数集 | main 分支 | **完全一致**（含 `--exact-tg`、`--emit-progress`），测试矩阵/指标算法未做任何修改 |
