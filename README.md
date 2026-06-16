# Video Understanding

自部署短视频理解流水线，面向 10-15 分钟中文抖音视频，分开拿三类信号：

- 画面内容：Qwen3-VL-32B-Instruct AWQ-INT4，卡 0 单卡 TP=1。
- 烧录字幕/OCR：同一 VL 请求内按抽帧时间戳识别。
- 音轨语音：卡 1 跑 faster-whisper/Whisper large，输出带时间戳转写。

输出会按时间戳融合成统一上下文，用于总结、打标、事实提取和 QA。

## 目录

- `configs/pipeline.yaml`：默认抽帧、服务 endpoint、ASR、融合与评测配置。
- `video_understanding/`：CLI、下载适配器和流水线代码。
- `scripts/launch_vllm_qwen3_vl_32b_awq.sh`：卡 0 主 VL 服务。
- `scripts/launch_vllm_qwen3_vl_8b_bf16.sh`：卡 2 吞吐副本或 8B 回退服务。
- `scripts/run_single_video.sh`：单条视频闭环。
- `docs/deployment.md`：3×A100 PCIe 部署和验证步骤。

## 安装

建议 Python 3.10 或 3.11。当前 vLLM/CUDA 生态通常不要用 Python 3.13 跑服务。

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[client,asr]"
pip install "vllm>=0.11.0" "qwen-vl-utils==0.0.14"
```

系统依赖：

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg
```

## 启动服务

卡 0，32B AWQ-INT4 主理解：

```bash
CUDA_VISIBLE_DEVICES=0 \
MODEL=/models/Qwen3-VL-32B-Instruct-AWQ \
PORT=8000 \
scripts/launch_vllm_qwen3_vl_32b_awq.sh
```

卡 2，如果需要吞吐或回退 8B：

```bash
CUDA_VISIBLE_DEVICES=2 \
MODEL=Qwen/Qwen3-VL-8B-Instruct \
PORT=8002 \
scripts/launch_vllm_qwen3_vl_8b_bf16.sh
```

## 单视频闭环

先把链接解析/下载到本地：

```bash
python -m video_understanding fetch "https://..."
```

下载层会按 `configs/pipeline.yaml` 的 `download.order` 依次尝试：

- `yt-dlp`：通用下载器。
- `twitter-video-downloader`：通过 `twittervideodownloader.com` 解析 Twitter/X 视频。
- `ideaflow`：通过 `parse.ideaflow.top` 解析抖音、小红书、快手、微博等链接。

也可以直接把 URL 或分享文本传给完整流水线，程序会先下载再分析：

```bash
python -m video_understanding run /path/to/video.mp4 --workdir runs/demo
python -m video_understanding run "https://..." --workdir runs/demo
```

生成文件：

- `runs/demo/visual.jsonl`：每个视频窗口的画面/OCR 输出。
- `runs/demo/asr.jsonl`：语音转写片段。
- `runs/demo/fused.jsonl`：按时间窗融合后的结构化上下文。
- `runs/demo/context.md`：给总结、QA、RAG 使用的文本上下文。
- `runs/demo/summary.md`：默认结构化总结。

单独 QA：

```bash
python -m video_understanding summarize \
  --context runs/demo/context.md \
  --output runs/demo/qa.md \
  --question "视频里提到的商品卖点和价格分别是什么？"
```

## A/B 验证

先跑本方案得到 `context.md`，再把 Qwen3-Omni-Thinking 的端到端输出存成 `omni.md`。

```bash
python -m video_understanding ab-eval \
  --vl-asr-context runs/demo/context.md \
  --omni-context runs/demo/omni.md \
  --output runs/demo/ab_report.md
```

这一步用于决定最终是否需要为非语音音频、音乐/情绪、音画联合理解引入 Omni。
