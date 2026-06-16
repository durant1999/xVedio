from __future__ import annotations

from pathlib import Path
from typing import Any

from .media import split_windows
from .utils import format_ts, read_jsonl, write_jsonl, write_text


def overlaps(row: dict[str, Any], start: float, end: float) -> bool:
    return float(row.get("start", 0)) < end and float(row.get("end", 0)) > start


def max_end(*collections: list[dict[str, Any]]) -> float:
    value = 0.0
    for rows in collections:
        for row in rows:
            value = max(value, float(row.get("end", 0.0)))
    return value


def fuse_rows(
    visual_rows: list[dict[str, Any]],
    asr_rows: list[dict[str, Any]],
    *,
    window_seconds: float,
) -> list[dict[str, Any]]:
    duration = max_end(visual_rows, asr_rows)
    blocks: list[dict[str, Any]] = []
    for index, (start, end) in enumerate(split_windows(duration, window_seconds)):
        visual_matches = [row for row in visual_rows if overlaps(row, start, end)]
        asr_matches = [row for row in asr_rows if overlaps(row, start, end)]
        blocks.append(
            {
                "index": index,
                "start": round(start, 3),
                "end": round(end, 3),
                "visual": [
                    {
                        "start": row.get("start"),
                        "end": row.get("end"),
                        "text": row.get("text", ""),
                    }
                    for row in visual_matches
                ],
                "speech": [
                    {
                        "start": row.get("start"),
                        "end": row.get("end"),
                        "text": row.get("text", ""),
                    }
                    for row in asr_matches
                ],
            }
        )
    return blocks


def render_context_markdown(blocks: list[dict[str, Any]]) -> str:
    lines: list[str] = ["# Video Context", ""]
    for block in blocks:
        start = format_ts(block["start"])
        end = format_ts(block["end"])
        lines.append(f"## {start}-{end}")
        lines.append("")
        lines.append("### Visual/OCR")
        visual = block.get("visual") or []
        if visual:
            for item in visual:
                item_start = format_ts(item.get("start", block["start"]))
                item_end = format_ts(item.get("end", block["end"]))
                lines.append(f"- [{item_start}-{item_end}] {item.get('text', '').strip()}")
        else:
            lines.append("- 无视觉/OCR记录")
        lines.append("")
        lines.append("### Speech")
        speech = block.get("speech") or []
        if speech:
            for item in speech:
                item_start = format_ts(item.get("start", block["start"]))
                item_end = format_ts(item.get("end", block["end"]))
                lines.append(f"- [{item_start}-{item_end}] {item.get('text', '').strip()}")
        else:
            lines.append("- 无语音记录")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def fuse_files(
    visual_path: str | Path,
    asr_path: str | Path,
    *,
    output_jsonl: str | Path,
    output_markdown: str | Path,
    window_seconds: float,
) -> list[dict[str, Any]]:
    visual_rows = read_jsonl(visual_path)
    asr_rows = read_jsonl(asr_path)
    blocks = fuse_rows(visual_rows, asr_rows, window_seconds=window_seconds)
    write_jsonl(output_jsonl, blocks)
    write_text(output_markdown, render_context_markdown(blocks))
    return blocks

