from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from video_understanding.cli import _write_progress


class CliProgressTests(unittest.TestCase):
    def test_write_progress_writes_json_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workdir = Path(temp_dir)

            _write_progress(
                workdir,
                stage="analyzing",
                vl_total=3,
                vl_done=1,
                asr_done=False,
            )

            progress = json.loads((workdir / "progress.json").read_text(encoding="utf-8"))
            self.assertEqual(progress["stage"], "analyzing")
            self.assertEqual(progress["vl_total"], 3)
            self.assertEqual(progress["vl_done"], 1)
            self.assertFalse(progress["asr_done"])
            self.assertFalse((workdir / "progress.json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
