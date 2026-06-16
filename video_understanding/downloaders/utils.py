from __future__ import annotations

import json
import mimetypes
import re
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any

from ..utils import PipelineError, ensure_dir, write_text


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

URL_RE = re.compile(r"https?://[^\s<>'\"，。；;、]+")
TRAILING_PUNCTUATION = ".,;:!?)]}，。；：！？）】》\"'“”‘’"


def extract_first_url(value: str) -> str | None:
    match = URL_RE.search(value)
    if not match:
        return None
    return match.group(0).rstrip(TRAILING_PUNCTUATION)


def host_matches(url: str, domains: set[str]) -> bool:
    hostname = urllib.parse.urlparse(url).hostname or ""
    hostname = hostname.lower()
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in domains)


def safe_filename(value: str | None, *, default: str = "media", max_length: int = 80) -> str:
    name = (value or default).strip() or default
    name = re.sub(r"[^\w.\-]+", "_", name, flags=re.UNICODE).strip("._")
    if not name:
        name = default
    return name[:max_length].strip("._") or default


def infer_extension(url: str, content_type: str | None = None, default: str = ".bin") -> str:
    suffix = Path(urllib.parse.urlparse(url).path).suffix
    if suffix:
        return suffix.split("?")[0]
    if content_type:
        guessed = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if guessed:
            return guessed
    return default


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 10000):
        candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise PipelineError(f"Unable to find a unique output path for {path}")


def normalize_media_url(url: str, *, base_url: str | None = None, prefer_https: bool = True) -> str:
    if url.startswith("//"):
        url = f"https:{url}" if prefer_https else f"http:{url}"
    if base_url:
        url = urllib.parse.urljoin(base_url, url)
    if prefer_https and url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    return url


def build_cookie_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))


def request_bytes(
    url: str,
    *,
    opener: urllib.request.OpenerDirector | None = None,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout_seconds: int = 120,
) -> tuple[bytes, dict[str, str]]:
    request_headers = {"User-Agent": DEFAULT_USER_AGENT}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    client = opener or urllib.request.build_opener()
    try:
        with client.open(request, timeout=timeout_seconds) as response:
            response_headers = {key.lower(): value for key, value in response.headers.items()}
            return response.read(), response_headers
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise PipelineError(f"HTTP {exc.code} from {url}: {body[:500]}") from exc
    except urllib.error.URLError as exc:
        raise PipelineError(f"Unable to reach {url}: {exc}") from exc


def request_text(
    url: str,
    *,
    opener: urllib.request.OpenerDirector | None = None,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout_seconds: int = 120,
) -> str:
    body, response_headers = request_bytes(
        url,
        opener=opener,
        method=method,
        data=data,
        headers=headers,
        timeout_seconds=timeout_seconds,
    )
    content_type = response_headers.get("content-type", "")
    encoding = "utf-8"
    match = re.search(r"charset=([^;\s]+)", content_type)
    if match:
        encoding = match.group(1)
    return body.decode(encoding, errors="replace")


def request_json(
    url: str,
    *,
    opener: urllib.request.OpenerDirector | None = None,
    headers: dict[str, str] | None = None,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    text = request_text(url, opener=opener, headers=headers, timeout_seconds=timeout_seconds)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PipelineError(f"Non-JSON response from {url}: {text[:300]}") from exc
    if not isinstance(payload, dict):
        raise PipelineError(f"JSON response from {url} must be an object")
    return payload


def download_url_to_file(
    url: str,
    output_dir: str | Path,
    *,
    filename: str,
    headers: dict[str, str] | None = None,
    timeout_seconds: int = 300,
) -> Path:
    target_dir = ensure_dir(output_dir)
    request_headers = {"User-Agent": DEFAULT_USER_AGENT}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            content_type = response.headers.get("content-type")
            extension = infer_extension(url, content_type, default=".bin")
            target_name = safe_filename(filename)
            if not Path(target_name).suffix:
                target_name += extension
            target = unique_path(target_dir / target_name)
            with target.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
            return target
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise PipelineError(f"HTTP {exc.code} while downloading {url}: {body[:500]}") from exc
    except urllib.error.URLError as exc:
        raise PipelineError(f"Unable to download {url}: {exc}") from exc


def write_download_metadata(output_dir: str | Path, payload: dict[str, Any]) -> Path:
    target = Path(output_dir) / "download_metadata.json"
    write_text(target, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return target
