import unittest

from video_understanding.fusion import fuse_rows, render_context_markdown


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


if __name__ == "__main__":
    unittest.main()

