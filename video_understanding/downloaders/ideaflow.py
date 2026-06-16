from __future__ import annotations

import urllib.parse
from pathlib import Path
from typing import Any

from ..utils import PipelineError
from .base import DownloadResult
from .utils import download_url_to_file, host_matches, normalize_media_url, request_json, safe_filename


IDEAFLOW_DOMAINS = {
    "douyin.com",
    "iesdouyin.com",
    "snssdk.com",
    "xiaohongshu.com",
    "xhslink.com",
    "kuaishou.com",
    "kuaishouapp.com",
    "gifshow.com",
    "huoshan.com",
    "ixigua.com",
    "weibo.com",
    "m.weibo.cn",
    "weishi.qq.com",
}


def _origin(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    return f"{parsed.scheme}://{parsed.netloc}/"


def _media_header_candidates(source_url: str, base_url: str) -> list[dict[str, str]]:
    browser_video_headers = {
        "Accept": "video/webm,video/mp4,video/*;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Range": "bytes=0-",
        "Sec-Fetch-Dest": "video",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "cross-site",
    }
    referrers = [
        None,
        source_url,
        _origin(source_url),
        base_url,
        _origin(base_url),
        "https://www.douyin.com/",
        "https://www.iesdouyin.com/",
    ]
    candidates: list[dict[str, str]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for referrer in referrers:
        headers = dict(browser_video_headers)
        if referrer:
            headers["Referer"] = referrer
        key = tuple(sorted(headers.items()))
        if key not in seen:
            candidates.append(headers)
            seen.add(key)
    return candidates


def download_ideaflow_media(
    media_url: str,
    output_dir: Path,
    *,
    filename: str,
    source_url: str,
    base_url: str,
    timeout_seconds: int,
) -> Path:
    errors: list[str] = []
    for headers in _media_header_candidates(source_url, base_url):
        try:
            return download_url_to_file(
                media_url,
                output_dir,
                filename=filename,
                headers=headers,
                timeout_seconds=timeout_seconds,
            )
        except PipelineError as exc:
            referrer = headers.get("Referer", "<none>")
            errors.append(f"Referer={referrer}: {exc}")
    detail = "\n".join(f"- {error}" for error in errors)
    raise PipelineError(f"Ideaflow media URL parsed but all download attempts failed:\n{detail}")


class IdeaflowDownloader:
    name = "ideaflow"
    default_base_url = "https://parse.ideaflow.top/"

    def supports(self, url: str) -> bool:
        return host_matches(url, IDEAFLOW_DOMAINS)

    def download(
        self,
        url: str,
        output_dir: Path,
        config: dict[str, Any] | None = None,
    ) -> DownloadResult:
        config = config or {}
        base_url = str(config.get("base_url") or self.default_base_url)
        timeout_seconds = int(config.get("timeout_seconds", 120))
        api_url = urllib.parse.urljoin(base_url, "/video/share/url/parse")
        api_url = f"{api_url}?url={urllib.parse.quote(url, safe='')}"
        payload = request_json(api_url, timeout_seconds=timeout_seconds)

        if payload.get("code") != 200:
            raise PipelineError(str(payload.get("msg") or f"Ideaflow parse failed: {payload}"))

        data = payload.get("data")
        if not isinstance(data, dict):
            raise PipelineError(f"Ideaflow response has no data object: {payload}")

        title = data.get("title") or "ideaflow_video"
        author = data.get("author") if isinstance(data.get("author"), dict) else {}
        author_name = author.get("name") if isinstance(author, dict) else None
        stem = safe_filename(title, default="ideaflow_video")
        files: list[Path] = []

        cover_path = None
        cover_url = data.get("cover_url")
        if isinstance(cover_url, str) and cover_url:
            cover_path = download_ideaflow_media(
                normalize_media_url(cover_url, base_url=base_url),
                output_dir,
                filename=f"{stem}_cover",
                source_url=url,
                base_url=base_url,
                timeout_seconds=timeout_seconds,
            )

        video_url = data.get("video_url")
        if isinstance(video_url, str) and video_url:
            video_path = download_ideaflow_media(
                normalize_media_url(video_url, base_url=base_url),
                output_dir,
                filename=f"{stem}.mp4",
                source_url=url,
                base_url=base_url,
                timeout_seconds=timeout_seconds,
            )
            files.append(video_path)

        images = data.get("images")
        image_items = images if isinstance(images, list) else []
        for index, item in enumerate(image_items):
            if not isinstance(item, dict):
                continue
            image_url = item.get("url")
            if isinstance(image_url, str) and image_url:
                files.append(
                    download_ideaflow_media(
                        normalize_media_url(image_url, base_url=base_url),
                        output_dir,
                        filename=f"{stem}_image_{index:03d}",
                        source_url=url,
                        base_url=base_url,
                        timeout_seconds=timeout_seconds,
                    )
                )
            live_photo_url = item.get("live_photo_url")
            if isinstance(live_photo_url, str) and live_photo_url:
                files.append(
                    download_ideaflow_media(
                        normalize_media_url(live_photo_url, base_url=base_url),
                        output_dir,
                        filename=f"{stem}_live_{index:03d}.mp4",
                        source_url=url,
                        base_url=base_url,
                        timeout_seconds=timeout_seconds,
                    )
                )

        if not files:
            raise PipelineError(f"Ideaflow parsed the URL but returned no downloadable media: {payload}")

        has_video = any(path.suffix.lower() in {".mp4", ".mov", ".m4v", ".webm"} for path in files)
        has_live = any(isinstance(item, dict) and item.get("live_photo_url") for item in image_items)
        if video_url:
            media_type = "video"
        elif has_live:
            media_type = "live_photo"
        else:
            media_type = "image_album" if not has_video else "video"

        return DownloadResult(
            source_url=url,
            page_url=url,
            title=str(title) if title else None,
            author=str(author_name) if author_name else None,
            media_type=media_type,
            files=files,
            cover=cover_path,
            metadata={"api_url": api_url, "response": payload},
        )
