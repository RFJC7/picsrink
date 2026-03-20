from __future__ import annotations

import io
import os
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, Literal

from PIL import Image, ImageOps

OutputFormat = Literal["AUTO", "JPEG", "PNG", "WEBP"]


@dataclass(frozen=True)
class ResizePreset:
    key: str
    label: str
    max_width: Optional[int]
    max_height: Optional[int]


PRESETS: Dict[str, ResizePreset] = {
    "ORIGINAL": ResizePreset("ORIGINAL", "原尺寸", None, None),
    "4096": ResizePreset("4096", "长边 4096", 4096, 4096),
    "3072": ResizePreset("3072", "长边 3072", 3072, 3072),
    "2560": ResizePreset("2560", "长边 2560", 2560, 2560),
    "2048": ResizePreset("2048", "长边 2048", 2048, 2048),
    "1980": ResizePreset("1980", "长边 1980", 1980, 1980),
    "1920": ResizePreset("1920", "长边 1920", 1920, 1920),
    "1600": ResizePreset("1600", "长边 1600", 1600, 1600),
    "1280": ResizePreset("1280", "长边 1280", 1280, 1280),
    "1080": ResizePreset("1080", "长边 1080", 1080, 1080),
    "1024": ResizePreset("1024", "长边 1024", 1024, 1024),
    "720": ResizePreset("720", "长边 720", 720, 720),
    "800x600": ResizePreset("800x600", "800×600（适配）", 800, 600),
    "640x480": ResizePreset("640x480", "640×480（适配）", 640, 480),
}


def parse_target_size(text: str) -> int:
    s = (text or "").strip().upper().replace(" ", "")
    if not s:
        raise ValueError("empty target size")
    mul = 1
    if s.endswith("KB"):
        mul = 1024
        s = s[:-2]
    elif s.endswith("MB"):
        mul = 1024 * 1024
        s = s[:-2]
    elif s.endswith("B"):
        mul = 1
        s = s[:-1]
    v = float(s)
    if v <= 0:
        raise ValueError("invalid target size")
    return int(v * mul)


def _has_alpha(im: Image.Image) -> bool:
    if im.mode in ("RGBA", "LA"):
        return True
    if im.mode == "P":
        return "transparency" in im.info
    return False


def _normalize(im: Image.Image) -> Image.Image:
    im = ImageOps.exif_transpose(im)
    if im.mode == "CMYK":
        im = im.convert("RGB")
    return im


def _fit_size(w: int, h: int, max_w: int, max_h: int) -> Tuple[int, int]:
    if max_w <= 0 or max_h <= 0:
        return w, h
    if w <= max_w and h <= max_h:
        return w, h
    sw = max_w / float(w)
    sh = max_h / float(h)
    s = min(sw, sh)
    nw = max(1, int(round(w * s)))
    nh = max(1, int(round(h * s)))
    return nw, nh


def apply_preset(im: Image.Image, preset: ResizePreset) -> Image.Image:
    im = _normalize(im)
    if preset.max_width is None or preset.max_height is None:
        return im
    w, h = im.size
    nw, nh = _fit_size(w, h, preset.max_width, preset.max_height)
    if (nw, nh) == (w, h):
        return im
    return im.resize((nw, nh), Image.Resampling.LANCZOS)


def apply_custom_resize(
    im: Image.Image, width: Optional[int], height: Optional[int], keep_aspect: bool = True
) -> Image.Image:
    im = _normalize(im)
    w0, h0 = im.size
    ww = int(width) if width is not None else None
    hh = int(height) if height is not None else None

    if ww is None and hh is None:
        return im

    if ww is not None and ww <= 0:
        raise ValueError("invalid custom width")
    if hh is not None and hh <= 0:
        raise ValueError("invalid custom height")

    if keep_aspect:
        if ww is None:
            ww = hh
        if hh is None:
            hh = ww
        assert ww is not None and hh is not None
        nw, nh = _fit_size(w0, h0, ww, hh)
        if (nw, nh) == (w0, h0):
            return im
        return im.resize((nw, nh), Image.Resampling.LANCZOS)

    if ww is None:
        ww = w0
    if hh is None:
        hh = h0
    if (ww, hh) == (w0, h0):
        return im
    return im.resize((int(ww), int(hh)), Image.Resampling.LANCZOS)


def choose_auto_format(im: Image.Image, src_format: Optional[str]) -> str:
    sf = (src_format or "").upper()
    if sf in ("JPEG", "JPG"):
        return "JPEG"
    if sf == "PNG":
        return "PNG"
    if sf == "WEBP":
        return "WEBP"
    return "PNG" if _has_alpha(im) else "JPEG"


def _encode_jpeg(im: Image.Image, quality: int) -> bytes:
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=int(quality), optimize=True, progressive=True)
    return buf.getvalue()


def _encode_webp(im: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="WEBP", quality=int(quality), method=6)
    return buf.getvalue()


def _encode_png_lossless(im: Image.Image, compress_level: int) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True, compress_level=int(compress_level))
    return buf.getvalue()


def _encode_png_palette(im: Image.Image, colors: int, compress_level: int) -> bytes:
    base = im
    if base.mode not in ("RGB", "RGBA"):
        base = base.convert("RGBA" if _has_alpha(base) else "RGB")
    pal = base.convert("P", palette=Image.Palette.ADAPTIVE, colors=int(colors))
    if _has_alpha(base):
        alpha = base.getchannel("A")
        mask = alpha.point(lambda a: 255 if a <= 0 else 0)
        pal.paste(0, mask=mask)
        pal.info["transparency"] = 0
    buf = io.BytesIO()
    pal.save(buf, format="PNG", optimize=True, compress_level=int(compress_level))
    return buf.getvalue()


def encode_best_effort(im: Image.Image, fmt: str) -> Tuple[bytes, str]:
    f = fmt.upper()
    if f == "JPEG":
        return _encode_jpeg(im, 85), "jpg"
    if f == "WEBP":
        return _encode_webp(im, 82), "webp"
    if f == "PNG":
        return _encode_png_lossless(im, 9), "png"
    raise ValueError(f"unsupported format: {fmt}")


def encode_to_target(im: Image.Image, fmt: str, target_bytes: int, tolerance: float = 0.06) -> Tuple[bytes, str]:
    if target_bytes <= 0:
        return encode_best_effort(im, fmt)

    f = fmt.upper()
    lo = int(target_bytes * (1.0 - float(tolerance)))
    hi = int(target_bytes * (1.0 + float(tolerance)))

    if f in ("JPEG", "WEBP"):
        enc = _encode_jpeg if f == "JPEG" else _encode_webp
        ext = "jpg" if f == "JPEG" else "webp"
        q_lo, q_hi = 10, 95
        best: Optional[bytes] = None
        best_diff = 1 << 62

        for _ in range(10):
            q = (q_lo + q_hi) // 2
            b = enc(im, q)
            n = len(b)
            d = abs(n - target_bytes)
            if d < best_diff:
                best, best_diff = b, d
            if lo <= n <= hi:
                return b, ext
            if n > target_bytes:
                q_hi = max(q_lo, q - 1)
            else:
                q_lo = min(q_hi, q + 1)

        if best is None:
            return enc(im, 75), ext
        return best, ext

    if f == "PNG":
        ext = "png"
        best: Optional[bytes] = None
        best_diff = 1 << 62

        for cl in (9, 6, 3):
            b = _encode_png_lossless(im, cl)
            n = len(b)
            d = abs(n - target_bytes)
            if d < best_diff:
                best, best_diff = b, d
            if lo <= n <= hi:
                return b, ext

        for colors in (256, 192, 160, 128, 96, 64, 48, 32, 24, 16, 8):
            for cl in (9, 6, 3):
                b = _encode_png_palette(im, colors, cl)
                n = len(b)
                d = abs(n - target_bytes)
                if d < best_diff:
                    best, best_diff = b, d
                if lo <= n <= hi:
                    return b, ext

        if best is None:
            return _encode_png_lossless(im, 9), ext
        return best, ext

    raise ValueError(f"unsupported format: {fmt}")


def encode_to_target_with_downscale(
    im: Image.Image, fmt: str, target_bytes: int, tolerance: float = 0.06
) -> Tuple[bytes, str, Image.Image]:
    b, ext = encode_to_target(im, fmt, target_bytes, tolerance=tolerance)
    if len(b) <= int(target_bytes * (1.0 + tolerance)):
        return b, ext, im

    w0, h0 = im.size
    cur = im

    for i in range(8):
        s = 0.92 ** (i + 1)
        nw = max(1, int(round(w0 * s)))
        nh = max(1, int(round(h0 * s)))
        if (nw, nh) == cur.size:
            continue
        cur = cur.resize((nw, nh), Image.Resampling.LANCZOS)
        b2, ext2 = encode_to_target(cur, fmt, target_bytes, tolerance=tolerance)
        if len(b2) < len(b):
            b, ext, im = b2, ext2, cur
        if len(b) <= int(target_bytes * (1.0 + tolerance)):
            return b, ext, im

    return b, ext, im


@dataclass(frozen=True)
class ProcessRequest:
    preset_key: str = "ORIGINAL"
    output_format: OutputFormat = "AUTO"
    target_size_bytes: Optional[int] = None
    allow_downscale: bool = True
    custom_width: Optional[int] = None
    custom_height: Optional[int] = None
    keep_aspect: bool = True


@dataclass(frozen=True)
class ProcessResult:
    data: bytes
    format: str
    ext: str
    width: int
    height: int
    size_bytes: int


def process_image_path(src_path: str, req: ProcessRequest) -> ProcessResult:
    with Image.open(src_path) as im0:
        im = im0.copy()
        src_fmt = im0.format

    preset = PRESETS.get(req.preset_key)
    if preset is None:
        raise ValueError(f"unknown preset: {req.preset_key}")

    pre_size = im.size
    if req.custom_width is not None or req.custom_height is not None:
        im = apply_custom_resize(im, req.custom_width, req.custom_height, keep_aspect=bool(req.keep_aspect))
    else:
        im = apply_preset(im, preset)

    out_fmt = choose_auto_format(im, src_fmt) if req.output_format == "AUTO" else req.output_format
    if req.target_size_bytes is None:
        data, ext = encode_best_effort(im, out_fmt)
    else:
        if req.allow_downscale:
            data, ext, im = encode_to_target_with_downscale(im, out_fmt, int(req.target_size_bytes))
        else:
            data, ext = encode_to_target(im, out_fmt, int(req.target_size_bytes))

    w, h = im.size
    return ProcessResult(
        data=data,
        format=out_fmt.upper(),
        ext=ext,
        width=int(w),
        height=int(h),
        size_bytes=int(len(data)),
    )


def suggest_output_path(src_path: str, ext: str, suffix: str = "_shrink") -> str:
    base, _ = os.path.splitext(src_path)
    return f"{base}{suffix}.{ext}"
