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
HTML_PREFIXES = (b"<!doctype", b"<html", b"<!DOCTYPE", b"<HTML")


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


def _is_direct_video_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    hostname = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    return hostname == "video.twimg.com" or path.endswith(".mp4")


def _video_url_from_href(href: str, *, base_url: str) -> str | None:
    normalized = normalize_media_url(html.unescape(href), base_url=base_url, prefer_https=False)
    if _is_direct_video_url(normalized):
        return normalized

    parsed = urllib.parse.urlparse(normalized)
    query_values = urllib.parse.parse_qs(parsed.query)
    for values in query_values.values():
        for value in values:
            value = html.unescape(urllib.parse.unquote(value))
            if _is_direct_video_url(value):
                return value
            match = MP4_URL_RE.search(value)
            if match:
                return html.unescape(match.group(0))
    return None


def extract_video_links(page_html: str, *, base_url: str) -> list[str]:
    candidates: list[str] = []
    for match in MP4_URL_RE.finditer(page_html):
        candidate = html.unescape(match.group(0))
        if _is_direct_video_url(candidate):
            candidates.append(candidate)

    parser = AnchorParser()
    parser.feed(page_html)
    for href, _text in parser.anchors:
        candidate = _video_url_from_href(href, base_url=base_url)
        if candidate:
            candidates.append(candidate)

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        unique.append(candidate)
    return sorted(unique, key=_video_score, reverse=True)


def _source_origin(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    return f"{parsed.scheme}://{parsed.netloc}/"


def _twitter_media_header_candidates(source_url: str) -> list[dict[str, str]]:
    base_headers = {
        "Accept": "video/webm,video/mp4,video/*;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Sec-Fetch-Dest": "video",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "cross-site",
    }
    referrers = [None, _source_origin(source_url), "https://x.com/", "https://twitter.com/"]
    candidates: list[dict[str, str]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for referrer in referrers:
        headers = dict(base_headers)
        if referrer:
            headers["Referer"] = referrer
        key = tuple(sorted(headers.items()))
        if key not in seen:
            candidates.append(headers)
            seen.add(key)
    return candidates


def _looks_like_mp4(path: Path) -> bool:
    with path.open("rb") as handle:
        header = handle.read(4096)
    stripped = header.lstrip()
    if any(stripped.startswith(prefix) for prefix in HTML_PREFIXES):
        return False
    return b"ftyp" in header[:64]


def download_twitter_media(
    media_url: str,
    output_dir: Path,
    *,
    filename: str,
    source_url: str,
    timeout_seconds: int,
) -> Path:
    errors: list[str] = []
    for headers in _twitter_media_header_candidates(source_url):
        referrer = headers.get("Referer", "<none>")
        try:
            path = download_url_to_file(
                media_url,
                output_dir,
                filename=filename,
                headers=headers,
                timeout_seconds=timeout_seconds,
            )
            if _looks_like_mp4(path):
                return path
            path.unlink(missing_ok=True)
            errors.append(f"Referer={referrer}: downloaded response was not an mp4")
        except PipelineError as exc:
            errors.append(f"Referer={referrer}: {exc}")
    detail = "\n".join(f"- {error}" for error in errors)
    raise PipelineError(f"Twitter media URL found but all download attempts failed:\n{detail}")


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
                path = download_twitter_media(
                    link,
                    output_dir,
                    filename=f"{stem}_{index:02d}.mp4",
                    source_url=url,
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
