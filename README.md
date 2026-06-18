# xVideo

面向中文短视频的自部署视频理解系统。V1 版本的目标是处理 10-15 分钟左右的抖音/短视频内容，同时提取三类信息：

- 画面内容：人物、场景、动作、商品、界面元素。
- 烧录字幕/OCR：视频里的字幕、价格、品牌、账号、页面文字。
- 音轨语音：口播、旁白、对话的带时间戳转写。

默认方案是 `Qwen3-VL-32B-Instruct-AWQ` 负责视觉/OCR，`faster-whisper` 负责 ASR，再按时间戳融合成统一上下文，用于总结、打标、事实提取和 QA。

## V1 Scope

V1 已覆盖：

- CLI 单视频闭环：下载/复制视频、时长保护、分段抽帧、VL、ASR、融合、总结/QA。
- VL/ASR 并行：`run` 流程中 ASR 线程和 VL 分段循环重叠执行。
- 细粒度进度：每个 job 的 `work/progress.json` 写入 `downloading/analyzing/fusing/summarizing/done` 阶段和 VL 分段计数。
- MCP server：给 Mac 本地 Codex 通过 SSH tunnel 调用。
- FastAPI BFF：给 Android/Web App 提供 REST/SSE、历史 job、追问、推送注册、帧画廊和视频播放文件服务。
- 磁盘保护：异步 job 成功后默认清理重媒体；需要 App 帧画廊/视频播放时可打开保留媒体。
- 安全默认：BFF/MCP 默认只绑定 `127.0.0.1`，BFF 除 `/healthz` 外强制 Bearer token。

当前不做：

- 不把完整 MP4 直接发给 VL 模型。VL 只收到按时间窗抽出的图片帧。
- 不让 VL 听音频。语音由 ASR 单独处理。
- 不把标题注入 VL 看图阶段。标题/作者/URL 只进入融合后的 `Source Metadata`，用于帮助总结理解主题和笑点，事实判断仍以 Visual/OCR/Speech 证据为准。

## Architecture

```text
video URL / local mp4
        |
        v
CLI pipeline: download -> probe -> split windows
        |                         |
        |                         +-> ASR thread: ffmpeg audio.wav -> faster-whisper -> asr.jsonl
        |
        +-> VL loop: ffmpeg frames -> vLLM Qwen3-VL -> visual.jsonl
        |
        v
fusion: visual.jsonl + asr.jsonl + download_metadata.json -> fused.jsonl + context.md
        |
        v
summary / QA -> summary.md
```

服务层：

```text
Mac Codex ---- SSH tunnel ---- MCP server :9000 ---- MCPJobManager

Phone/App ---- Mac/VPN tunnel ---- BFF :8788 ---- MCPJobManager
                                            |
                                            +---- python -m video_understanding run
                                            +---- runs/mcp_jobs/<job_id>/

VL calls -------------------------------> vLLM :8000
ASR runs locally on GPU 1 through faster-whisper
```

`MCPJobManager` 是异步任务的共享核心。MCP server 和 BFF 都复用它，因此手机 App 和 Codex 可以看到同一份 `runs/mcp_jobs/` 作业历史。

## Repository Layout

- `configs/pipeline.yaml`：下载、抽帧、VL、ASR、融合、总结配置。
- `video_understanding/`：CLI、下载器、VL client、ASR、融合、总结、MCP job manager。
- `server/`：FastAPI BFF，服务 Android/Web App。
- `scripts/manage_vl_server.sh`：后台管理 vLLM 服务。
- `scripts/launch_vllm_qwen3_vl_32b_awq.sh`：32B AWQ vLLM 前台启动器。
- `scripts/launch_vllm_qwen3_vl_8b_bf16.sh`：8B bf16 回退或吞吐副本启动器。
- `scripts/launch_mcp_server.sh`：MCP HTTP server 启动器。
- `scripts/run_single_video.sh`：单条视频 CLI 便捷脚本。
- `docs/deployment.md`：3xA100 PCIe 部署细节、A/B 验证和安全说明。

## Environment

推荐 Python 3.11。当前服务器环境名是 `vedio_understand`；新机器可以沿用这个名字，也可以用 `CONDA_ENV` 覆盖启动脚本里的环境名。

```bash
conda activate vedio_understand
```

安装依赖：

```bash
pip install -U pip
pip install -e ".[client,asr,server,mcp]"
pip install "qwen-vl-utils==0.0.14"
```

当前已验证组合：

- `vllm==0.11.0`
- `transformers>=4.57.1,<5`
- `qwen-vl-utils==0.0.14`
- `faster-whisper`
- `ffmpeg`
- `yt-dlp`

`transformers` 不要升到 5.x；vLLM 0.11 的 tokenizer 缓存逻辑仍依赖 4.x 属性。

系统依赖：

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg
```

## Models

默认 VL 权重：

```bash
hf download QuantTrio/Qwen3-VL-32B-Instruct-AWQ \
  --local-dir models/Qwen3-VL-32B-Instruct-AWQ \
  --max-workers 3
```

`models/` 已被 `.gitignore` 忽略，不应提交到 GitHub。

ASR 默认使用 `faster-whisper` 的 `large-v3`。首次运行会下载模型；也可以提前触发：

```bash
python -c "from faster_whisper import WhisperModel; WhisperModel('large-v3', device='cuda', device_index=1, compute_type='float16')"
```

## Start And Stop

### vLLM

建议把 vLLM 也绑定到 loopback，由本机 CLI/BFF 调用：

```bash
CONDA_ENV=vedio_understand \
HOST=127.0.0.1 \
CUDA_VISIBLE_DEVICES=0 \
PORT=8000 \
MAX_MODEL_LEN=131072 \
LIMIT_MM_IMAGES=80 \
scripts/manage_vl_server.sh start
```

检查：

```bash
scripts/manage_vl_server.sh status
curl http://127.0.0.1:8000/v1/models
```

停止：

```bash
scripts/manage_vl_server.sh stop
```

空闲时 `nvidia-smi` 的 `GPU-Util=0%` 是正常的。判断服务是否加载成功主要看 `/v1/models`、vLLM 日志和显存占用。

### BFF

BFF 给手机 App 调用，默认监听 `127.0.0.1:8788`。

```bash
cd server
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(32))"  # 填入 XVIDEO_API_TOKEN
```

常用 `.env`：

```bash
XVIDEO_HOST=127.0.0.1
XVIDEO_PORT=8788
XVIDEO_ENABLE_JOBS=1
XVIDEO_JOB_ROOT=runs/mcp_jobs
XVIDEO_CONFIG_PATH=configs/pipeline.yaml
XVIDEO_KEEP_MEDIA=0

# 服务器需要通过 Mac 代理下载视频或访问 Expo push API 时使用
http_proxy=http://127.0.0.1:9999
https_proxy=http://127.0.0.1:9999
no_proxy=127.0.0.1,localhost
```

启动：

```bash
cd server
tmux new -d -s xvideo-bff './run.sh'
```

检查：

```bash
curl http://127.0.0.1:8788/healthz
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8788/ping
```

停止：

```bash
tmux kill-session -t xvideo-bff
```

App 如果需要帧画廊和原视频播放，必须在提交新 job 前设置：

```bash
XVIDEO_KEEP_MEDIA=1
```

否则成功 job 会删除 `source/` 原视频、`frames/` 和 `audio.wav`，`/frames` 会为空，`/video` 会返回 404。旧 job 已删除的媒体无法恢复。

### MCP Server

MCP 给 Mac 本地 Codex 调用。推荐 GPU 服务器只监听 `127.0.0.1:9000`，Mac 通过 SSH tunnel 访问。

```bash
CONDA_ENV=vedio_understand scripts/launch_mcp_server.sh
```

默认地址：

```text
http://127.0.0.1:9000/mcp
```

Mac SSH tunnel：

```bash
ssh -L 9000:127.0.0.1:9000 gpu-server
```

Mac 的 `~/.codex/config.toml`：

```toml
[mcp_servers.video_understanding]
url = "http://127.0.0.1:9000/mcp"
tool_timeout_sec = 120
```

## CLI Usage

完整处理本地视频：

```bash
python -m video_understanding run /path/to/video.mp4 --workdir runs/demo
```

完整处理 URL 或分享文案：

```bash
python -m video_understanding run "https://v.douyin.com/xxxx/" --workdir runs/demo
```

带问题：

```bash
python -m video_understanding run "https://v.douyin.com/xxxx/" \
  --workdir runs/demo \
  --question "这个视频搞笑的点在哪里？"
```

默认超过 30 分钟的视频会在抽帧、ASR、VL 前拒绝分析。临时调整：

```bash
python -m video_understanding run /path/to/video.mp4 \
  --workdir runs/demo \
  --max-duration-seconds 1800
```

`--max-duration-seconds 0` 可关闭本次 CLI 运行的限制；BFF/MCP 不暴露放宽入口，仍按配置保护队列。

只下载：

```bash
python -m video_understanding fetch "https://v.douyin.com/xxxx/" --output-dir runs/downloads
```

只跑视觉/OCR：

```bash
python -m video_understanding vl /path/to/video.mp4 --workdir runs/demo
```

只跑 ASR：

```bash
python -m video_understanding asr /path/to/video.mp4 --workdir runs/demo
```

只融合已有结果：

```bash
python -m video_understanding fuse \
  --visual runs/demo/visual.jsonl \
  --asr runs/demo/asr.jsonl \
  --output-jsonl runs/demo/fused.jsonl \
  --output-markdown runs/demo/context.md \
  --metadata runs/demo/source/download_metadata.json
```

基于融合上下文追问：

```bash
python -m video_understanding summarize \
  --context runs/demo/context.md \
  --output runs/demo/qa.md \
  --question "视频里提到的商品卖点和价格分别是什么？"
```

## Pipeline Outputs

直接 CLI 运行默认保留所有中间文件：

- `source/`：下载或复制过来的原视频，以及 `download_metadata.json`。
- `frames/`：按时间窗抽出的 JPG 帧。
- `audio.wav`：从视频抽取的 16kHz 单声道音频。
- `progress.json`：当前阶段和 VL/ASR 进度。
- `visual.jsonl`：每个时间窗的画面/OCR 输出。
- `asr.jsonl`：语音转写片段。
- `fused.jsonl`：按时间窗融合后的结构化上下文。
- `context.md`：给总结、QA、RAG 使用的文本上下文，顶部包含不可信 Source Metadata 背景。
- `summary.md`：默认结构化总结或问题回答。

`progress.json` 常见阶段：

- `downloading`
- `analyzing`
- `fusing`
- `summarizing`
- `done`

BFF/MCP 异步 job 成功后默认清理重资产：

- 删除：`work/source/` 下除 `download_metadata.json` 之外的媒体文件、`work/frames/`、`work/audio.wav`。
- 保留：`state.json`、`job.log`、`summary.md`、`context.md`、`fused.jsonl`、`visual.jsonl`、`asr.jsonl`、`progress.json`、`download_metadata.json`。

失败、取消或状态未知的 job 会保留现场，方便排查。

## BFF API

所有接口除 `/healthz` 外都需要：

```text
Authorization: Bearer <XVIDEO_API_TOKEN>
```

核心接口：

- `GET /healthz`：开放健康检查。
- `GET /ping`：鉴权检查。
- `POST /jobs`：提交 URL、分享文案或服务器本地视频路径。
- `GET /jobs`：历史列表。
- `GET /jobs/{job_id}`：任务状态。
- `GET /jobs/{job_id}/events`：SSE 状态流。
- `POST /jobs/{job_id}/cancel`：取消任务。
- `GET /jobs/{job_id}/artifact/{name}`：读取文本产物，例如 `summary`、`context`、`visual`、`asr`、`fused`、`progress`、`log`、`download_metadata`。
- `POST /jobs/{job_id}/ask`：基于已有 `context.md` 追问。
- `POST /devices`：注册 Expo push token，完成/失败/取消时推送。
- `GET /jobs/{job_id}/frames`：返回每段代表帧，需要媒体未被清理。
- `GET /jobs/{job_id}/file?path=...`：受保护的图片/视频/wav 文件读取。
- `GET /jobs/{job_id}/video`：返回保留的源视频，支持浏览器/播放器 Range 请求。

文件服务有路径穿越和扩展名白名单保护，只能读取 job workdir 内的图片、视频和 wav。

## MCP Tools

Codex 可用工具：

- `get_server_info`
- `submit_video_job`
- `get_job_status`
- `list_jobs`
- `get_job_artifact`
- `ask_video`
- `cancel_job`

推荐调用流程：

```text
submit_video_job -> get_job_status -> get_job_artifact(summary/context/progress) -> ask_video
```

不要让 MCP 工具同步等待完整 10-15 分钟视频处理；提交后轮询状态即可。

## Tuning

主要参数在 `configs/pipeline.yaml`：

- `video.fps`：默认 1。漏短动作时升到 2；成本近似翻倍。
- `video.segment_seconds`：默认 45。单段图片数约为 `fps * segment_seconds`。
- `video.max_side`：默认 960。OCR 不清楚时可升高；显存/延迟压力大时降低。
- `video.max_duration_seconds`：默认 1800，即 30 分钟。
- `vl.max_tokens`：每段视觉/OCR 输出长度。
- `asr.device_index`：默认 1，即第二张 GPU。
- `summary.max_tokens`：最终总结或 QA 输出长度。

`LIMIT_MM_IMAGES` 要覆盖单段图片数。默认 `45s * 1fps = 45`，服务脚本示例用 `LIMIT_MM_IMAGES=80`。

## A/B Evaluation

把当前 VL+ASR 输出和 Omni 端到端输出做对比：

```bash
python -m video_understanding ab-eval \
  --vl-asr-context runs/demo/context.md \
  --omni-context runs/demo/omni.md \
  --output runs/demo/ab_report.md
```

建议用 5-10 条真实样本覆盖：

- 纯口播/旁白。
- 大量烧录字幕。
- 商品、价格、优惠、品牌信息。
- 音乐或情绪驱动内容。
- 需要精确片段定位的内容。

决策规则：

- 差距主要来自 OCR、画面细节、商品/界面文字：继续优化 VL+ASR。
- 差距主要来自非语音音频、音乐情绪、音画联合事件：评估引入 Omni。
- 差距主要来自定位：优先做视频 RAG/embedding，而不是盲目加大 VL 模型。

## Security

- BFF 和 MCP 默认绑定 `127.0.0.1`，通过 SSH tunnel、VPN 或受控反向代理访问。
- BFF 除 `/healthz` 外全部强制 Bearer token；`.env` 不提交。
- vLLM 建议也绑定 `127.0.0.1`，只给本机 CLI/BFF 调用。
- 不要把 BFF/MCP/vLLM 直接绑定公网地址。
- `runs/`、`models/`、`logs/`、`.run/` 都不应提交。
- 公开 GitHub 仓库不会让运行中的服务自动暴露；真正决定可访问性的是监听地址、防火墙、SSH/VPN 转发和 token。

## GitHub Hygiene

这些目录不应提交：

- `models/`
- `runs/`
- `downloads/`
- `logs/`
- `.run/`
- `__pycache__/`

提交前检查：

```bash
git status --short
```

同时检查 token、私钥、绝对 home 路径、本机用户名和下载样本。

## V2 TODO

- 增加断点续跑：`--skip-asr`、`--skip-vl`、`--skip-fusion`，长视频失败后无需重跑全部阶段。
- 增加本地 ASR 模型路径配置，避免生产环境首次运行联网下载 `large-v3`。
- 增加 Qwen3-ASR backend，与 faster-whisper 做中文口播质量对比。
- 为 MCP HTTP 增加内建 Bearer token 校验，减少对反向代理鉴权的依赖。
- 增加视频下载器真实站点集成测试和失败样例记录。
- 增加批量任务队列和多 VL 副本 router，支持 GPU 0/2 并发刷量。
- 增加 embedding/RAG：按 `context.md` 时间窗切 chunk，支持精确片段检索。
- 增加 A/B 评测模板，固化 VL+ASR vs Omni 的人工复核字段。
- 增加 systemd unit 或其他守护方式，规范生产部署和开机恢复。
- 增加 CI：unit tests、shellcheck、README 命令 smoke test。
