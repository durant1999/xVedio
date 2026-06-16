from __future__ import annotations

from pathlib import Path
from typing import Any

from ..utils import PipelineError, ensure_dir, require_binary, run_command
from .base import DownloadResult


class YtDlpDownloader:
    name = "yt-dlp"

    def supports(self, url: str) -> bool:
        return url.startswith(("http://", "https://"))

    def download(
        self,
        url: str,
        output_dir: Path,
        config: dict[str, Any] | None = None,
    ) -> DownloadResult:
        require_binary("yt-dlp")
        config = config or {}
        target_dir = ensure_dir(output_dir)
        before = {path.resolve() for path in target_dir.glob("*") if path.is_file()}
        output_template = str(target_dir / "%(title).80s-%(id)s.%(ext)s")

        command = [
            "yt-dlp",
            "--merge-output-format",
            "mp4",
            "--no-warnings",
            "--print",
            "after_move:filepath",
            "-o",
            output_template,
        ]
        if config.get("no_playlist", True):
            command.append("--no-playlist")
        if config.get("format"):
            command.extend(["-f", str(config["format"])])
        command.append(url)

        result = run_command(command, label="yt-dlp download")
        paths = [Path(line.strip()) for line in result.stdout.splitlines() if line.strip()]
        files = [path for path in paths if path.exists()]

        if not files:
            after = {path.resolve() for path in target_dir.glob("*") if path.is_file()}
            files = sorted((Path(path) for path in after - before), key=lambda path: path.stat().st_mtime)
        if not files:
            raise PipelineError(f"yt-dlp did not produce a file under {target_dir}")

        return DownloadResult(
            source_url=url,
            page_url=url,
            title=files[0].stem,
            media_type="video",
            files=files,
            metadata={
                "command": command[:1] + ["..."],
                "stdout": result.stdout.strip(),
            },
        )
