from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from video_understanding.downloaders.base import DownloadResult
from video_understanding.downloaders.ideaflow import IdeaflowDownloader, download_ideaflow_media
from video_understanding.downloaders.registry import download_url
from video_understanding.downloaders.twitter_video_downloader import (
    download_twitter_media,
    extract_hidden_inputs,
    extract_video_links,
)
from video_understanding.downloaders.utils import extract_first_url
from video_understanding.utils import PipelineError


class DownloaderUtilityTests(unittest.TestCase):
    def test_extract_first_url_from_share_text(self):
        text = "复制这条内容 https://v.douyin.com/abc123/?foo=bar&x=1，打开看看"

        self.assertEqual(extract_first_url(text), "https://v.douyin.com/abc123/?foo=bar&x=1")

    def test_twitter_hidden_inputs_are_extracted(self):
        page = """
        <form>
          <input type="hidden" name="csrfmiddlewaretoken" value="csrf-value">
          <input type="hidden" name="gql" value="gql-value">
        </form>
        """

        self.assertEqual(
            extract_hidden_inputs(page),
            {"csrfmiddlewaretoken": "csrf-value", "gql": "gql-value"},
        )

    def test_twitter_video_links_are_sorted_by_resolution(self):
        page = """
        <a href="https://video.twimg.com/ext_tw_video/1/vid/640x360/a.mp4?tag=10">Download</a>
        <a href="https://video.twimg.com/ext_tw_video/1/vid/1280x720/b.mp4?tag=10">Download</a>
        <a href="/en/">Download Another Video</a>
        """

        links = extract_video_links(page, base_url="https://twittervideodownloader.com/en/")

        self.assertEqual(links[0], "https://video.twimg.com/ext_tw_video/1/vid/1280x720/b.mp4?tag=10")
        self.assertEqual(len(links), 2)

    def test_twitter_media_download_rejects_html_and_retries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            html_path = Path(temp_dir) / "bad.mp4"
            video_path = Path(temp_dir) / "good.mp4"

            def fake_download(url, output_dir, *, headers, **kwargs):
                if headers.get("Referer") is None:
                    html_path.write_bytes(b"<!DOCTYPE html><html>not video</html>")
                    return html_path
                video_path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\0" * 128)
                return video_path

            with mock.patch(
                "video_understanding.downloaders.twitter_video_downloader.download_url_to_file",
                side_effect=fake_download,
            ) as patched:
                path = download_twitter_media(
                    "https://video.twimg.com/ext_tw_video/1/vid/1280x720/b.mp4",
                    Path(temp_dir),
                    filename="video.mp4",
                    source_url="https://x.com/user/status/1",
                    timeout_seconds=120,
                )

        self.assertEqual(path, video_path)
        self.assertGreaterEqual(patched.call_count, 2)


class IdeaflowDownloaderTests(unittest.TestCase):
    def test_ideaflow_downloads_video_and_cover_from_api_response(self):
        payload = {
            "code": 200,
            "data": {
                "title": "测试视频",
                "author": {"name": "作者"},
                "cover_url": "https://cdn.example/cover.jpg",
                "video_url": "https://cdn.example/video.mp4",
            },
        }

        def fake_download(url, output_dir, *, filename, **kwargs):
            path = Path(output_dir) / filename
            path.write_bytes(url.encode("utf-8"))
            return path

        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch(
                "video_understanding.downloaders.ideaflow.request_json",
                return_value=payload,
            ), mock.patch(
                "video_understanding.downloaders.ideaflow.download_url_to_file",
                side_effect=fake_download,
            ):
                result = IdeaflowDownloader().download(
                    "https://v.douyin.com/example/",
                    Path(temp_dir),
                    {"base_url": "https://parse.ideaflow.top/"},
                )

        self.assertEqual(result.media_type, "video")
        self.assertEqual(result.title, "测试视频")
        self.assertEqual(result.author, "作者")
        self.assertEqual(len(result.files), 1)
        self.assertTrue(str(result.files[0]).endswith(".mp4"))
        self.assertIsNotNone(result.cover)

    def test_ideaflow_media_download_retries_header_variants(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "video.mp4"

            def fake_download(url, output_dir, *, filename, headers, **kwargs):
                if headers.get("Referer") is None:
                    raise PipelineError("HTTP 403 while downloading")
                output.write_bytes(b"video")
                return output

            with mock.patch(
                "video_understanding.downloaders.ideaflow.download_url_to_file",
                side_effect=fake_download,
            ) as patched:
                path = download_ideaflow_media(
                    "https://cdn.example/video.mp4",
                    Path(temp_dir),
                    filename="video.mp4",
                    source_url="https://www.douyin.com/video/123",
                    base_url="https://parse.ideaflow.top/",
                    timeout_seconds=120,
                )

        self.assertEqual(path, output)
        self.assertGreaterEqual(patched.call_count, 2)


class RegistryTests(unittest.TestCase):
    def test_registry_falls_back_after_downloader_failure(self):
        class FailingDownloader:
            name = "failing"

            def supports(self, url):
                return True

            def download(self, url, output_dir, config=None):
                raise PipelineError("boom")

        class SuccessDownloader:
            name = "success"

            def supports(self, url):
                return True

            def download(self, url, output_dir, config=None):
                path = Path(output_dir) / "video.mp4"
                path.write_bytes(b"video")
                return DownloadResult(source_url=url, files=[path], media_type="video")

        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch(
                "video_understanding.downloaders.registry.DOWNLOADER_FACTORIES",
                {"failing": FailingDownloader, "success": SuccessDownloader},
            ):
                result = download_url(
                    "look https://example.com/video",
                    temp_dir,
                    config={"order": ["failing", "success"]},
                )

            self.assertEqual(result.downloader, "success")
            self.assertEqual(result.primary_video_path.name, "video.mp4")
            metadata = json.loads((Path(temp_dir) / "download_metadata.json").read_text())
            self.assertEqual(metadata["original_input"], "look https://example.com/video")
            self.assertEqual(metadata["title"], None)


if __name__ == "__main__":
    unittest.main()
