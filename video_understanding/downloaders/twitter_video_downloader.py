from __future__ import annotations

import html
import re
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from ..utils import PipelineError
from .base import DownloadResult
from .utils import (
    build_cookie_opener,
    download_url_to_file,
    host_matches,
    normalize_media_url,
    request_text,
    safe_filename,
)


TWITTER_DOMAINS = {"twitter.com", "x.com"}
MP4_URL_RE = re.compile(r"https?://[^\"'<>\s]+?\.mp4(?:\?[^\"'<>\s]+)?")
RESOLUTION_RE = re.compile(r"(?P<width>\d{3,5})x(?P<height>\d{3,5})")


class HiddenInputParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hidden_inputs: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "input":
            return
        values = {key.lower(): value or "" for key, value in attrs}
        if values.get("type", "").lower() != "hidden":
            return
        name = values.get("name")
        if name:
            self.hidden_inputs[name] = values.get("value", "")


class AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.anchors: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        values = {key.lower(): value or "" for key, value in attrs}
        href = values.get("href")
        if href:
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href:
            self.anchors.append((self._href, " ".join(self._text).strip()))
            self._href = None
            self._text = []


def extract_hidden_inputs(page_html: str) -> dict[str, str]:
    parser = HiddenInputParser()
    parser.feed(page_html)
    return parser.hidden_inputs


def _video_score(url: str) -> int:
    scores = []
    for match in RESOLUTION_RE.finditer(url):
        scores.append(int(match.group("width")) * int(match.group("height")))
    return max(scores) if scores else 0


def extract_video_links(page_html: str, *, base_url: str) -> list[str]:
    candidates: list[str] = []
    for match in MP4_URL_RE.finditer(page_html):
        candidates.append(html.unescape(match.group(0)))

    parser = AnchorParser()
    parser.feed(page_html)
    for href, text in parser.anchors:
        normalized = normalize_media_url(html.unescape(href), base_url=base_url, prefer_https=False)
        lower = normalized.lower()
        label = text.lower()
        if ".mp4" in lower or "video.twimg.com" in lower or "download" in label:
            candidates.append(normalized)

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        unique.append(candidate)
    return sorted(unique, key=_video_score, reverse=True)


class TwitterVideoDownloader:
    name = "twitter-video-downloader"
    default_base_url = "https://twittervideodownloader.com/en/"

    def supports(self, url: str) -> bool:
        return host_matches(url, TWITTER_DOMAINS)

    def download(
        self,
        url: str,
        output_dir: Path,
        config: dict[str, Any] | None = None,
    ) -> DownloadResult:
        config = config or {}
        base_url = str(config.get("base_url") or self.default_base_url)
        timeout_seconds = int(config.get("timeout_seconds", 120))
        opener = build_cookie_opener()
        home_html = request_text(base_url, opener=opener, timeout_seconds=timeout_seconds)
        hidden_inputs = extract_hidden_inputs(home_html)
        if "csrfmiddlewaretoken" not in hidden_inputs:
            raise PipelineError("TwitterVideoDownloader page did not expose a CSRF token")

        form = dict(hidden_inputs)
        form["tweet"] = url
        post_data = urllib.parse.urlencode(form).encode("utf-8")
        post_url = urllib.parse.urljoin(base_url, "/download")
        result_html = request_text(
            post_url,
            opener=opener,
            method="POST",
            data=post_data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": base_url,
                "Origin": urllib.parse.urljoin(base_url, "/").rstrip("/"),
            },
            timeout_seconds=timeout_seconds,
        )

        links = extract_video_links(result_html, base_url=base_url)
        if not links:
            raise PipelineError("TwitterVideoDownloader returned no mp4 links")

        tweet_id = Path(urllib.parse.urlparse(url).path).name or "twitter_video"
        stem = safe_filename(f"twitter_{tweet_id}", default="twitter_video")
        errors: list[str] = []
        for index, link in enumerate(links):
            try:
                path = download_url_to_file(
                    link,
                    output_dir,
                    filename=f"{stem}_{index:02d}.mp4",
                    headers={"Referer": base_url},
                    timeout_seconds=timeout_seconds,
                )
                return DownloadResult(
                    source_url=url,
                    page_url=url,
                    title=stem,
                    media_type="video",
                    files=[path],
                    metadata={
                        "base_url": base_url,
                        "post_url": post_url,
                        "candidate_count": len(links),
                        "selected_url": link,
                    },
                )
            except PipelineError as exc:
                errors.append(f"{link}: {exc}")

        detail = "\n".join(f"- {error}" for error in errors)
        raise PipelineError(f"TwitterVideoDownloader found links but download failed:\n{detail}")
