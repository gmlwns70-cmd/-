"""썸네일 자동 생성 (1280x720 JPG, 유튜브 권장 크기).

배경은 이 영상에 실제로 쓰인 소재(내 소재 / 허락 소재 / 무료 스톡)의 장면이나,
사용자가 직접 올린 사진만 사용합니다.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageEnhance, ImageFilter

from .assets import resolve_path
from .config import UserFacingError, load_config
from .project import Project
from .subtitles import _load_font, find_font, wrap_lines

THUMB_SIZE = (1280, 720)

# 색 조합: (첫 줄 글자색, 둘째 줄 강조색, 테두리색)
THEMES: dict[str, tuple[str, str, str]] = {
    "노랑 + 흰색": ("#FFFFFF", "#FFE14D", "#000000"),
    "흰색 + 빨강": ("#FFFFFF", "#FF3B3B", "#000000"),
    "흰색 + 민트": ("#FFFFFF", "#3DF5C8", "#0B1F1A"),
    "검정 + 노랑 (밝은 배경용)": ("#111111", "#E8A000", "#FFFFFF"),
}
LAYOUTS = {"left": "왼쪽 큰 글씨", "center": "가운데 큰 글씨", "bottom": "아래 띠 배너"}


def cover_image(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    w, h = size
    scale = max(w / img.width, h / img.height)
    img = img.resize((max(w, round(img.width * scale)), max(h, round(img.height * scale))), Image.LANCZOS)
    left, top = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def candidate_frames(project: Project, limit: int = 6) -> list[Image.Image]:
    """영상에 쓰인 소재에서 배경 후보 장면을 뽑습니다. (hook 장면 먼저)"""
    data = project.load_scenes() or {}
    scenes = sorted(data.get("scenes", []), key=lambda s: (s.get("type") != "hook", s.get("id", 0)))
    frames: list[Image.Image] = []
    seen: set[str] = set()
    for sc in scenes:
        for m in sc.get("media", []):
            if len(frames) >= limit:
                return frames
            if m.get("kind") not in ("video", "image") or m["path"] in seen:
                continue
            path = resolve_path(project, m["path"])
            if not path.exists():
                continue
            seen.add(m["path"])
            try:
                if m["kind"] == "image":
                    frames.append(Image.open(path).convert("RGB"))
                else:
                    from moviepy import VideoFileClip
                    with VideoFileClip(str(path), audio=False) as clip:
                        t = min(max((clip.duration or 1) / 3, 0), max((clip.duration or 1) - 0.1, 0))
                        frames.append(Image.fromarray(clip.get_frame(t)).convert("RGB"))
            except Exception:
                continue
    return frames


def _fit_font(lines: list[str], font_path: str | None, max_w: int, max_h: int, stroke_ratio: float,
              start: int = 170, minimum: int = 48):
    size = start
    while size > minimum:
        font = _load_font(font_path, size)
        sw = max(2, int(size * stroke_ratio))
        draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        widths = [draw.textbbox((0, 0), ln, font=font, stroke_width=sw)[2] for ln in lines]
        total_h = int(size * 1.12) * len(lines)
        if max(widths) <= max_w and total_h <= max_h:
            return font, size, sw
        size -= 6
    return _load_font(font_path, minimum), minimum, max(2, int(minimum * stroke_ratio))


def make_thumbnail(background: Image.Image, text: str, layout: str = "left", theme: str = "노랑 + 흰색",
                   font_path: str | None = None, max_chars: int = 7) -> Image.Image:
    """배경 + 큰 문구(2~3줄, 줄마다 색을 번갈아) 썸네일을 만듭니다."""
    W, H = THUMB_SIZE
    main_c, accent_c, stroke_c = THEMES.get(theme, next(iter(THEMES.values())))
    bg = cover_image(background.convert("RGB"), THUMB_SIZE)
    bg = ImageEnhance.Contrast(ImageEnhance.Color(bg).enhance(1.25)).enhance(1.1)
    img = bg.convert("RGBA")

    # 글자가 잘 보이도록 어두운 그라데이션
    xs, ys = np.meshgrid(np.arange(W), np.arange(H))
    if layout == "left":
        a = np.clip(1 - xs / (W * 0.75), 0, 1)
    elif layout == "bottom":
        a = np.clip((ys - H * 0.45) / (H * 0.55), 0, 1)
    else:
        a = np.full((H, W), 0.55)
    shade = Image.fromarray((190 * a).astype(np.uint8))
    dark = Image.new("RGBA", THUMB_SIZE, (0, 0, 0, 255))
    dark.putalpha(shade)
    img.alpha_composite(dark)

    words = text.replace("\n", " ").strip() or " "
    lines = wrap_lines(words, max_chars + 5 if layout == "bottom" else max_chars)[:3]
    if layout == "left":
        box = (60, 60, int(W * 0.66), H - 120)
    elif layout == "bottom":
        box = (60, int(H * 0.42), W - 60, H - 50)
    else:
        box = (80, 80, W - 80, H - 160)
    max_w, max_h = box[2] - box[0], box[3] - box[1]
    font, size, sw = _fit_font(lines, font_path, max_w, max_h, stroke_ratio=0.09)
    line_h = int(size * 1.12)
    block_h = line_h * len(lines)
    y0 = box[1] + (max_h - block_h) // 2 if layout != "bottom" else box[3] - block_h

    shadow = Image.new("RGBA", THUMB_SIZE, (0, 0, 0, 0))
    text_layer = Image.new("RGBA", THUMB_SIZE, (0, 0, 0, 0))
    sd, td = ImageDraw.Draw(shadow), ImageDraw.Draw(text_layer)
    for i, ln in enumerate(lines):
        bbox = td.textbbox((0, 0), ln, font=font, stroke_width=sw)
        lw = bbox[2] - bbox[0]
        x = box[0] - bbox[0] if layout == "left" else (W - lw) // 2 - bbox[0]
        y = y0 + i * line_h - bbox[1] // 2
        color = accent_c if i % 2 == 1 or len(lines) == 1 else main_c
        off = max(4, size // 18)
        sd.text((x + off, y + off), ln, font=font, fill=(0, 0, 0, 200), stroke_width=sw, stroke_fill=(0, 0, 0, 200))
        td.text((x, y), ln, font=font, fill=color, stroke_width=sw, stroke_fill=stroke_c)
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(6)))
    img.alpha_composite(text_layer)

    # 아래 띠 배너 레이아웃은 강조색 막대를 추가
    if layout == "bottom":
        ImageDraw.Draw(img).rectangle([0, H - 18, W, H], fill=ImageColor.getrgb(accent_c))
    elif layout == "left":
        ImageDraw.Draw(img).rectangle([box[0], y0 - 28, box[0] + 140, y0 - 14], fill=ImageColor.getrgb(accent_c))
    return img.convert("RGB")


def generate_thumbnails(project: Project, text: str | None = None, theme: str = "노랑 + 흰색",
                        background: Image.Image | None = None, frame_index: int = 0,
                        layouts: list[str] | None = None, cfg: dict | None = None) -> list[Path]:
    """레이아웃별 썸네일을 output/thumbnail_*.jpg 로 저장합니다."""
    cfg = cfg or load_config()
    script = project.load_script() or {}
    text = (text if text is not None else script.get("thumbnail_text") or script.get("title") or "").strip()
    if not text:
        raise UserFacingError("❌ 썸네일 문구가 없어요. 문구를 입력하거나 ② 대본 탭의 '썸네일 문구'를 채워 주세요.")
    if background is None:
        frames = candidate_frames(project)
        if not frames:
            raise UserFacingError("❌ 배경으로 쓸 소재가 없어요. ④ 소재 단계를 먼저 하거나, 배경 사진을 직접 올려 주세요.")
        background = frames[min(frame_index, len(frames) - 1)]
    font = find_font(cfg["subtitles"].get("font_file", ""))
    outputs = []
    for layout in layouts or list(LAYOUTS):
        img = make_thumbnail(background, text, layout, theme, str(font) if font else None)
        out = project.output_dir / f"thumbnail_{layout}.jpg"
        img.save(out, "JPEG", quality=90, optimize=True)  # 유튜브 제한 2MB 이하
        outputs.append(out)
    return outputs
