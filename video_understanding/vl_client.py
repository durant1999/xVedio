from __future__ import annotations

import base64
import json
import mimetypes
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .utils import PipelineError, format_ts


VISUAL_SYSTEM_PROMPT = """你是一个严谨的视频理解标注员。输入是一段视频按时间戳抽出的连续帧。
目标是同时识别画面内容和烧录字幕/OCR。只根据可见画面作答，不要猜测音轨。
输出中文，按时间顺序保留时间戳。重点覆盖：人物/场景/动作/物品/品牌/界面文字/屏幕字幕/镜头变化/可能的广告或带货信息。
如果字幕不清楚，标为“疑似”或“无法确认”。"""


def _endpoint(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def post_json(
    base_url: str,
    path: str,
    payload: dict[str, Any],
    *,
    api_key: str | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        _endpoint(base_url, path),
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise PipelineError(f"HTTP {exc.code} from {request.full_url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise PipelineError(f"Unable to reach {request.full_url}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PipelineError(f"Non-JSON response from {request.full_url}") from exc


def image_to_data_url(path: str | Path) -> str:
    image_path = Path(path)
    mime_type = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def chat_completion(
    *,
    base_url: str,
    api_key: str | None,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    response = post_json(
        base_url,
        "/chat/completions",
        payload,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
    if "choices" not in response:
        raise PipelineError(f"Chat completion response has no choices: {response}")
    return response


def first_message_text(response: dict[str, Any]) -> str:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise PipelineError(f"Unable to parse chat completion response: {response}") from exc
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [part.get("text", "") for part in content if isinstance(part, dict)]
        return "\n".join(part for part in parts if part).strip()
    return str(content).strip()


def build_visual_messages(
    frames: list[dict[str, Any]],
    *,
    segment_start: float,
    segment_end: float,
    extra_prompt: str | None = None,
) -> list[dict[str, Any]]:
    frame_times = ", ".join(format_ts(frame["timestamp"]) for frame in frames)
    user_content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"视频片段范围：{format_ts(segment_start)}-{format_ts(segment_end)}。\n"
                f"帧时间戳：{frame_times}。\n"
                "请输出：\n"
                "1. 时间线画面描述，每条带时间范围；\n"
                "2. OCR/烧录字幕逐条提取，尽量保留原文；\n"
                "3. 关键实体、商品、地点、账号/界面元素；\n"
                "4. 可能影响内容理解的遗漏或不确定项。\n"
            ),
        }
    ]
    if extra_prompt:
        user_content.append({"type": "text", "text": extra_prompt})

    for frame in frames:
        user_content.append({"type": "text", "text": f"FRAME {format_ts(frame['timestamp'])}"})
        user_content.append(
            {
                "type": "image_url",
                "image_url": {"url": image_to_data_url(frame["path"])},
            }
        )

    return [
        {"role": "system", "content": VISUAL_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def analyze_visual_segment(
    frames: list[dict[str, Any]],
    *,
    segment_start: float,
    segment_end: float,
    base_url: str,
    api_key: str | None,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout_seconds: int,
    extra_prompt: str | None = None,
) -> dict[str, Any]:
    messages = build_visual_messages(
        frames,
        segment_start=segment_start,
        segment_end=segment_end,
        extra_prompt=extra_prompt,
    )
    response = chat_completion(
        base_url=base_url,
        api_key=api_key,
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
    )
    return {
        "start": round(segment_start, 3),
        "end": round(segment_end, 3),
        "frames": [
            {"timestamp": frame["timestamp"], "path": frame["path"], "index": frame["index"]}
            for frame in frames
        ],
        "model": model,
        "text": first_message_text(response),
        "usage": response.get("usage", {}),
    }

