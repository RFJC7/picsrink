import os
import tempfile
import unittest

from PIL import Image

from picshrink.engine import PRESETS, ProcessRequest, parse_target_size, process_image_path


class EngineTests(unittest.TestCase):
    def test_parse_target_size(self):
        self.assertEqual(parse_target_size("1KB"), 1024)
        self.assertEqual(parse_target_size("2 MB"), 2 * 1024 * 1024)
        self.assertEqual(parse_target_size("512B"), 512)

    def test_resize_preset_exists(self):
        self.assertIn("800x600", PRESETS)
        self.assertEqual(PRESETS["800x600"].max_width, 800)
        self.assertEqual(PRESETS["800x600"].max_height, 600)

    def test_process_jpeg_target_size(self):
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "src.png")
            im = Image.new("RGB", (2000, 1400), color=(30, 120, 200))
            im.save(src, format="PNG", optimize=True)

            req = ProcessRequest(preset_key="800x600", output_format="JPEG", target_size_bytes=parse_target_size("200KB"))
            res = process_image_path(src, req)

            self.assertEqual(res.ext, "jpg")
            self.assertLessEqual(res.width, 800)
            self.assertLessEqual(res.height, 600)
            self.assertGreater(res.size_bytes, 0)
            self.assertLessEqual(res.size_bytes, parse_target_size("260KB"))

    def test_process_auto_format_alpha_prefers_png(self):
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "src.png")
            im = Image.new("RGBA", (400, 300), color=(10, 20, 30, 0))
            im.save(src, format="PNG", optimize=True)

            req = ProcessRequest(preset_key="ORIGINAL", output_format="AUTO", target_size_bytes=None)
            res = process_image_path(src, req)
            self.assertEqual(res.ext, "png")


if __name__ == "__main__":
    unittest.main()

