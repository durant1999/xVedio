from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..utils import PipelineError


VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}


@dataclass
class DownloadResult:
    source_url: str
    page_url: str | None = None
    title: str | None = None
    author: str | None = None
    media_type: str = "video"
    files: list[Path] = field(default_factory=list)
    cover: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    downloader: str | None = None

    @property
    def video_files(self) -> list[Path]:
        return [path for path in self.files if path.suffix.lower() in VIDEO_SUFFIXES]

    @property
    def primary_video_path(self) -> Path:
        videos = self.video_files
        if not videos:
            raise PipelineError(
                f"Download succeeded but no video file was produced for {self.source_url}"
            )
        return videos[0]


class Downloader(Protocol):
    name: str

    def supports(self, url: str) -> bool:
        ...

    def download(
        self,
        url: str,
        output_dir: Path,
        config: dict[str, Any] | None = None,
    ) -> DownloadResult:
        ...
