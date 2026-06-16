from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable


class PipelineError(RuntimeError):
    """Raised for expected pipeline failures with actionable messages."""


def ensure_dir(path: str | Path) -> Path:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def require_binary(name: str) -> str:
    resolved = shutil.which(name)
    if not resolved:
        raise PipelineError(
            f"Required binary '{name}' was not found on PATH. Install it before running this step."
        )
    return resolved


def run_command(command: list[str], *, label: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise PipelineError(f"{label} failed because '{command[0]}' is not installed.") from exc
    except subprocess.CalledProcessError as exc:
        details = exc.stderr.strip() or exc.stdout.strip()
        raise PipelineError(f"{label} failed: {details}") from exc


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise PipelineError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
    return rows


def write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    output = Path(path)
    ensure_dir(output.parent)
    with output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def write_text(path: str | Path, text: str) -> None:
    output = Path(path)
    ensure_dir(output.parent)
    output.write_text(text, encoding="utf-8")


def format_ts(seconds: float | int) -> str:
    total = max(0, int(round(float(seconds))))
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def env_or_value(value: str | None, env_name: str, default: str = "") -> str:
    if value and value != f"${{{env_name}}}":
        return value
    return os.getenv(env_name, default)


def coerce_float(value: Any, default: float) -> float:
    if value is None:
        return default
    return float(value)


def coerce_int(value: Any, default: int) -> int:
    if value is None:
        return default
    return int(value)

