from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware

from server.app import settings as settings_module
from server.app.auth import require_auth
from server.app.jobs import (
    _find_source_video,
    _list_representative_frames,
    _safe_path,
    get_manager,
)
from server.app.main import app


class FakeJobManager:
    def __init__(self, workdir: Path | None):
        self.workdir = workdir

    def public_state(self, job_id: str) -> dict[str, str]:
        state: dict[str, str] = {"job_id": job_id}
        if self.workdir is not None:
            state["workdir"] = str(self.workdir)
        return state


class BFFServerTests(unittest.TestCase):
    def tearDown(self) -> None:
        settings_module.get_settings.cache_clear()

    def test_default_repo_root_is_current_checkout(self):
        settings_module.get_settings.cache_clear()
        repo_root = Path(__file__).resolve().parents[1]

        self.assertEqual(Path(settings_module.DEFAULT_REPO_ROOT), repo_root)
        self.assertEqual(Path(settings_module.get_settings().repo_root), repo_root)

    def test_settings_allow_repo_root_override(self):
        with patch.dict(os.environ, {"XVIDEO_REPO_ROOT": "/tmp/xvideo"}, clear=False):
            settings_module.get_settings.cache_clear()
            self.assertEqual(settings_module.get_settings().repo_root, "/tmp/xvideo")

    def test_settings_parse_keep_media_flag(self):
        with patch.dict(os.environ, {"XVIDEO_KEEP_MEDIA": "1"}, clear=False):
            settings_module.get_settings.cache_clear()
            self.assertTrue(settings_module.get_settings().keep_media)

        with patch.dict(os.environ, {"XVIDEO_KEEP_MEDIA": "0"}, clear=False):
            settings_module.get_settings.cache_clear()
            self.assertFalse(settings_module.get_settings().keep_media)

    def test_auth_fails_closed_without_configured_token(self):
        with patch.dict(os.environ, {"XVIDEO_API_TOKEN": ""}, clear=False):
            settings_module.get_settings.cache_clear()
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(require_auth(None))

        self.assertEqual(ctx.exception.status_code, 503)

    def test_auth_accepts_matching_bearer_token(self):
        with patch.dict(os.environ, {"XVIDEO_API_TOKEN": "secret-token"}, clear=False):
            settings_module.get_settings.cache_clear()
            asyncio.run(require_auth("Bearer secret-token"))

            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(require_auth("Bearer wrong-token"))

        self.assertEqual(ctx.exception.status_code, 401)

    def test_get_manager_requires_lifespan_initialized_manager(self):
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(job_manager=None)))

        with self.assertRaises(HTTPException) as ctx:
            get_manager(request)  # type: ignore[arg-type]

        self.assertEqual(ctx.exception.status_code, 503)

        manager = object()
        request.app.state.job_manager = manager
        self.assertIs(get_manager(request), manager)  # type: ignore[arg-type]

    def test_cors_middleware_allows_app_clients(self):
        middleware = next(item for item in app.user_middleware if item.cls is CORSMiddleware)

        self.assertEqual(middleware.kwargs["allow_origins"], ["*"])
        self.assertEqual(middleware.kwargs["allow_methods"], ["*"])
        self.assertEqual(middleware.kwargs["allow_headers"], ["*"])

    def test_safe_path_serves_only_allowed_files_inside_workdir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workdir = Path(temp_dir)
            frame = workdir / "frames" / "0000_000000_000045" / "frame.jpg"
            frame.parent.mkdir(parents=True)
            frame.write_bytes(b"jpg")
            note = workdir / "note.txt"
            note.write_text("no", encoding="utf-8")
            outside = workdir.parent / "outside.jpg"
            outside.write_bytes(b"jpg")

            self.assertEqual(
                _safe_path(workdir, "frames/0000_000000_000045/frame.jpg"),
                frame,
            )

            with self.assertRaises(HTTPException) as ctx:
                _safe_path(workdir, "../outside.jpg")
            self.assertEqual(ctx.exception.status_code, 403)

            with self.assertRaises(HTTPException) as ctx:
                _safe_path(workdir, "note.txt")
            self.assertEqual(ctx.exception.status_code, 403)

            with self.assertRaises(HTTPException) as ctx:
                _safe_path(workdir, "missing.jpg")
            self.assertEqual(ctx.exception.status_code, 404)

    def test_list_frames_returns_representative_frame_per_segment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workdir = Path(temp_dir)
            segment = workdir / "frames" / "0000_000000_000045"
            segment.mkdir(parents=True)
            (segment / "frame_000001.jpg").write_bytes(b"1")
            (segment / "frame_000002.jpg").write_bytes(b"2")
            manager = FakeJobManager(workdir)

            result = _list_representative_frames(manager, "job-1")

            self.assertEqual(
                result,
                [
                    {
                        "path": "frames/0000_000000_000045/frame_000002.jpg",
                        "start": 0,
                        "end": 45,
                    }
                ],
            )

    def test_find_source_video_uses_largest_retained_video(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workdir = Path(temp_dir)
            source = workdir / "source"
            source.mkdir()
            small = source / "small.mp4"
            large = source / "large.mp4"
            small.write_bytes(b"1")
            large.write_bytes(b"1" * 8)
            manager = FakeJobManager(workdir)

            self.assertEqual(_find_source_video(manager, "job-1"), large)

    def test_find_source_video_404s_when_media_was_cleaned(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = FakeJobManager(Path(temp_dir))

            with self.assertRaises(HTTPException) as ctx:
                _find_source_video(manager, "job-1")

            self.assertEqual(ctx.exception.status_code, 404)
            self.assertIn("XVIDEO_KEEP_MEDIA=1", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()
