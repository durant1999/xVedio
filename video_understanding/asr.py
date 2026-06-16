from __future__ import annotations

from pathlib import Path
from typing import Any

from .utils import PipelineError


def transcribe_faster_whisper(
    audio_path: str | Path,
    *,
    model_name: str,
    device: str,
    device_index: int,
    compute_type: str,
    language: str | None,
    beam_size: int,
) -> list[dict[str, Any]]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise PipelineError(
            "faster-whisper is not installed. Install the ASR extra or choose another backend."
        ) from exc

    model = WhisperModel(
        model_name,
        device=device,
        device_index=device_index,
        compute_type=compute_type,
    )
    segments, info = model.transcribe(
        str(audio_path),
        language=language,
        beam_size=beam_size,
        vad_filter=True,
    )
    rows: list[dict[str, Any]] = []
    for index, segment in enumerate(segments):
        rows.append(
            {
                "index": index,
                "start": round(float(segment.start), 3),
                "end": round(float(segment.end), 3),
                "text": segment.text.strip(),
                "language": getattr(info, "language", language),
                "backend": "faster-whisper",
                "model": model_name,
            }
        )
    return rows


def transcribe_audio(audio_path: str | Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    backend = config.get("backend", "faster-whisper")
    if backend == "faster-whisper":
        return transcribe_faster_whisper(
            audio_path,
            model_name=config.get("model", "large-v3"),
            device=config.get("device", "cuda"),
            device_index=int(config.get("device_index", 0)),
            compute_type=config.get("compute_type", "float16"),
            language=config.get("language"),
            beam_size=int(config.get("beam_size", 5)),
        )
    raise PipelineError(f"Unsupported ASR backend: {backend}")

