from __future__ import annotations

from pathlib import Path
from typing import Any

from ..utils import PipelineError, ensure_dir
from .base import DownloadResult, Downloader
from .ideaflow import IdeaflowDownloader
from .twitter_video_downloader import TwitterVideoDownloader
from .utils import extract_first_url, write_download_metadata
from .yt_dlp import YtDlpDownloader


DOWNLOADER_FACTORIES: dict[str, type[Downloader]] = {
    "yt-dlp": YtDlpDownloader,
    "twitter-video-downloader": TwitterVideoDownloader,
    "ideaflow": IdeaflowDownloader,
}

DEFAULT_ORDER = ["yt-dlp", "twitter-video-downloader", "ideaflow"]


def _downloader_config(config: dict[str, Any], name: str) -> dict[str, Any]:
    value = config.get(name, {})
    return value if isinstance(value, dict) else {}


def build_downloaders(config: dict[str, Any] | None = None) -> list[Downloader]:
    config = config or {}
    order = config.get("order") or DEFAULT_ORDER
    downloaders: list[Downloader] = []
    for name in order:
        factory = DOWNLOADER_FACTORIES.get(str(name))
        if not factory:
            continue
        item_config = _downloader_config(config, str(name))
        if item_config.get("enabled", True) is False:
            continue
        downloaders.append(factory())
    return downloaders


def serialize_result(result: DownloadResult, *, original_input: str | None = None) -> dict[str, Any]:
    return {
        "downloader": result.downloader,
        "original_input": original_input,
        "source_url": result.source_url,
        "page_url": result.page_url,
        "title": result.title,
        "author": result.author,
        "media_type": result.media_type,
        "files": [str(path) for path in result.files],
        "cover": str(result.cover) if result.cover else None,
        "metadata": result.metadata,
    }


def download_url(
    source: str,
    output_dir: str | Path,
    *,
    config: dict[str, Any] | None = None,
) -> DownloadResult:
    url = extract_first_url(source)
    if not url:
        raise PipelineError(f"No http/https URL found in input: {source}")

    target_dir = ensure_dir(output_dir)
    errors: list[str] = []
    config = config or {}

    for downloader in build_downloaders(config):
        item_config = _downloader_config(config, downloader.name)
        if not downloader.supports(url):
            continue
        try:
            result = downloader.download(url, target_dir, item_config)
            result.downloader = result.downloader or downloader.name
            write_download_metadata(target_dir, serialize_result(result, original_input=source))
            return result
        except PipelineError as exc:
            errors.append(f"{downloader.name}: {exc}")

    if errors:
        detail = "\n".join(f"- {error}" for error in errors)
        raise PipelineError(f"All downloaders failed for {url}:\n{detail}")
    raise PipelineError(f"No downloader is configured for URL: {url}")
