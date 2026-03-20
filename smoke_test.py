import os
import tempfile

from PIL import Image

from picshrink.engine import ProcessRequest, parse_target_size, process_image_path


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        src_dir = os.path.join(td, "src")
        out_dir = os.path.join(td, "out")
        os.makedirs(src_dir, exist_ok=True)
        os.makedirs(out_dir, exist_ok=True)

        src1 = os.path.join(src_dir, "solid.png")
        src2 = os.path.join(src_dir, "alpha.png")

        Image.new("RGB", (2400, 1600), color=(30, 120, 200)).save(src1, format="PNG", optimize=True)
        Image.new("RGBA", (1200, 900), color=(10, 20, 30, 0)).save(src2, format="PNG", optimize=True)

        req1 = ProcessRequest(preset_key="800x600", output_format="JPEG", target_size_bytes=parse_target_size("200KB"))
        res1 = process_image_path(src1, req1)
        with open(os.path.join(out_dir, f"solid.{res1.ext}"), "wb") as f:
            f.write(res1.data)

        req2 = ProcessRequest(preset_key="ORIGINAL", output_format="AUTO", target_size_bytes=None)
        res2 = process_image_path(src2, req2)
        with open(os.path.join(out_dir, f"alpha.{res2.ext}"), "wb") as f:
            f.write(res2.data)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

