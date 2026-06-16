from __future__ import annotations

from typing import Any

from .utils import read_text, write_text
from .vl_client import chat_completion, first_message_text


AB_SYSTEM_PROMPT = """你是视频理解系统评测员。你会比较两个方案对同一视频的输出。
评测重点：漏掉的信息、OCR准确性、语音转写覆盖、时间戳定位、事实错误、部署成本/复杂度。
不要默认任何方案更好，必须用证据说明。"""


def build_ab_prompt(vl_asr_context: str, omni_context: str) -> str:
    return f"""请比较方案 A 和方案 B，并输出：
1. 总体结论；
2. A 相对 B 漏掉的信息；
3. B 相对 A 漏掉的信息；
4. OCR、语音、画面理解、时间戳四项评分，1-5 分；
5. 哪些视频类型需要 Omni，哪些类型 VL+ASR 足够；
6. 下一轮验证应增加的样本。

方案 A：VL+ASR 融合输出
{vl_asr_context}

方案 B：Omni 端到端输出
{omni_context}
"""


def evaluate_ab(
    vl_asr_context_path: str,
    omni_context_path: str,
    output_path: str,
    *,
    config: dict[str, Any],
) -> str:
    vl_asr_context = read_text(vl_asr_context_path)
    omni_context = read_text(omni_context_path)
    messages = [
        {"role": "system", "content": AB_SYSTEM_PROMPT},
        {"role": "user", "content": build_ab_prompt(vl_asr_context, omni_context)},
    ]
    response = chat_completion(
        base_url=config["judge_base_url"],
        api_key=config.get("judge_api_key"),
        model=config["judge_model"],
        messages=messages,
        temperature=0.0,
        max_tokens=int(config.get("max_tokens", 2400)),
        timeout_seconds=int(config.get("timeout_seconds", 600)),
    )
    text = first_message_text(response)
    write_text(output_path, text + "\n")
    return text

