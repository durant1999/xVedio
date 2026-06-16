# Deployment Runbook

## 固定决策

- 质量优先：默认 `Qwen3-VL-32B-Instruct`，AWQ-INT4，单卡 TP=1。
- A100 PCIe 没有 NVLink：避免跨卡 TP/EP，不使用 TP=3；最多 TP=2，默认不用。
- 长视频瓶颈主要是 KV cache 和视觉 token：`max-model-len` 卡到 128K，客户端分段抽帧并压缩分辨率。
- 卡 0：32B-INT4 主 VL/OCR。
- 卡 1：ASR。
- 卡 2：按吞吐需求起第二个 VL 副本，或给 embedding/RAG。

## 1. 环境

推荐 Python 3.10/3.11、CUDA 驱动匹配 vLLM wheel。

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[client,asr,server]"
sudo apt-get install -y ffmpeg
```

如果用 URL 输入，需要 `yt-dlp`；如果只处理本地 mp4，可以不走下载命令。

## 2. 权重

优先找 `Qwen3-VL-32B-Instruct` 的 AWQ-INT4 社区量化权重。没有可用量化版时，用：

```bash
pip install -e ".[quant]"
MODEL_PATH=/models/Qwen3-VL-32B-Instruct \
OUTPUT_PATH=/models/Qwen3-VL-32B-Instruct-AWQ \
scripts/quantize_qwen3_vl_awq.sh
```

自量化前先用 5-10 条真实样本做小批校准和人工检查，避免 OCR 细节劣化。

## 3. 卡 0 启动 VL

```bash
CUDA_VISIBLE_DEVICES=0 \
MODEL=/models/Qwen3-VL-32B-Instruct-AWQ \
SERVED_MODEL_NAME=Qwen/Qwen3-VL-32B-Instruct-AWQ \
PORT=8000 \
MAX_MODEL_LEN=131072 \
LIMIT_MM_IMAGES=80 \
scripts/launch_vllm_qwen3_vl_32b_awq.sh
```

`LIMIT_MM_IMAGES` 需要和客户端分段长度、fps 匹配。默认 45 秒 × 1 fps 约 45 张，留出余量。

## 4. 卡 1 跑 ASR

默认 CLI 用 faster-whisper 本地加载 `large-v3`：

```bash
CUDA_VISIBLE_DEVICES=1 python -m video_understanding asr /path/to/video.mp4 --workdir runs/demo
```

如果换 Qwen3-ASR，把 `video_understanding/asr.py` 增加对应 backend，保持输出字段 `start/end/text` 不变即可。

## 5. 单条闭环

```bash
python -m video_understanding run /path/to/video.mp4 --workdir runs/demo
```

长视频建议先保持：

- `fps: 1.0`
- `segment_seconds: 45`
- `max_side: 960`

如果漏短动作，把 fps 调到 2；如果 KV/显存压力明显，先降 `segment_seconds`，再降 `max_side`。

## 6. A/B 验证关口

取 5-10 个真实抖音片段，覆盖：

- 纯口播/旁白；
- 大量烧录字幕；
- 商品/价格/优惠信息；
- 音乐或情绪驱动内容；
- 需要精确片段定位的内容。

每条视频都产出：

- `context.md`：VL+ASR 融合输出。
- `omni.md`：Qwen3-Omni-Thinking 端到端输出。
- `ab_report.md`：用 `ab-eval` 生成的比较报告，再人工复核。

决策规则：

- 主要差距来自 OCR、画面细节、商品/界面文字：继续优化 VL+ASR。
- 主要差距来自非语音音频、音乐情绪、音画联合事件：保留 Omni 路线。
- 主要差距来自定位：卡 2 优先上 embedding/RAG，而不是盲目加大 VL。

## 7. 卡 2

吞吐优先：

```bash
CUDA_VISIBLE_DEVICES=2 PORT=8002 scripts/launch_vllm_qwen3_vl_8b_bf16.sh
```

质量优先且预算允许：卡 2 起第二个 32B-AWQ 副本，把上游任务按视频维度分发到 `:8000` 和 `:8002`。

精确定位优先：卡 2 放 embedding，按 `context.md` 的时间窗切 chunk，建立视频 RAG。

