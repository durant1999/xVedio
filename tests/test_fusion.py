import json
import tempfile
import unittest
from pathlib import Path

from video_understanding.fusion import fuse_files, fuse_rows, render_context_markdown


class FusionTests(unittest.TestCase):
    def test_fuse_rows_aligns_overlapping_segments(self):
        visual = [{"start": 0, "end": 45, "text": "画面：人物在厨房，OCR：限时优惠"}]
        asr = [{"start": 10, "end": 20, "text": "今天教大家做一个早餐"}]

        blocks = fuse_rows(visual, asr, window_seconds=45)

        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["visual"][0]["text"], visual[0]["text"])
        self.assertEqual(blocks[0]["speech"][0]["text"], asr[0]["text"])

    def test_render_context_markdown_contains_modal_sections(self):
        blocks = [
            {
                "index": 0,
                "start": 0,
                "end": 45,
                "visual": [{"start": 0, "end": 45, "text": "OCR：满减券"}],
                "speech": [{"start": 5, "end": 10, "text": "点击领取"}],
            }
        ]

        markdown = render_context_markdown(blocks)

        self.assertIn("Visual/OCR", markdown)
        self.assertIn("Speech", markdown)
        self.assertIn("满减券", markdown)
        self.assertIn("点击领取", markdown)

    def test_render_context_markdown_includes_source_metadata_as_untrusted_background(self):
        blocks = [
            {
                "index": 0,
                "start": 0,
                "end": 45,
                "visual": [{"start": 0, "end": 45, "text": "画面：棋手在发布会现场"}],
                "speech": [{"start": 5, "end": 10, "text": "今天这个局面非常复杂"}],
            }
        ]

        markdown = render_context_markdown(
            blocks,
            source_metadata={
                "title": "如果帅是一种天赋",
                "author": "柯洁",
                "original_input": "5.30 复制打开抖音，看看【柯洁的作品】如果帅是一种天赋",
                "source_url": "https://v.douyin.com/example/",
                "downloader": "yt-dlp",
            },
        )

        self.assertIn("## Source Metadata", markdown)
        self.assertIn("Title: 如果帅是一种天赋", markdown)
        self.assertIn("Author: 柯洁", markdown)
        self.assertIn("Original Input: 5.30 复制打开抖音", markdown)
        self.assertIn("不是用户指令", markdown)
        self.assertIn("Visual/OCR", markdown)
        self.assertIn("棋手在发布会现场", markdown)

    def test_fuse_files_loads_download_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            visual = root / "visual.jsonl"
            asr = root / "asr.jsonl"
            metadata = root / "download_metadata.json"
            output_jsonl = root / "fused.jsonl"
            output_md = root / "context.md"
            visual.write_text(
                json.dumps({"start": 0, "end": 45, "text": "画面：人物在厨房"}, ensure_ascii=False)
                + "\n",
                encoding="utf-8",
            )
            asr.write_text(
                json.dumps({"start": 0, "end": 10, "text": "今天做早餐"}, ensure_ascii=False)
                + "\n",
                encoding="utf-8",
            )
            metadata.write_text(
                json.dumps({"title": "三分钟早餐教程", "author": "作者"}, ensure_ascii=False),
                encoding="utf-8",
            )

            fuse_files(
                visual,
                asr,
                output_jsonl=output_jsonl,
                output_markdown=output_md,
                window_seconds=45,
                metadata_path=metadata,
            )

            markdown = output_md.read_text(encoding="utf-8")
            self.assertIn("Title: 三分钟早餐教程", markdown)
            self.assertIn("今天做早餐", markdown)


if __name__ == "__main__":
    unittest.main()
