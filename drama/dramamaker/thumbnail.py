"""회차별 썸네일 자동 제작: 세로(1080x1920, 쇼츠·릴스 표지) + 가로(1280x720, 유튜브 일반 영상).

배경 장면은 이 순서로 고릅니다.
  1) clips/EP01/thumb.png (또는 .jpg)  ← 직접 고른 장면
  2) 대본이 고른 썸네일 컷(thumbnail_cut)의 영상 → 가운데 장면
  3) 그 컷의 시작 이미지(cut05.png 등)
  4) 다른 컷 중 인물이 가장 많이 나오는 컷의 영상/이미지
  5) 아무것도 없으면 노을빛 그라데이션 배경
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from . import edit, subtitle_style
from .settings import BASE_DIR

PINK = (255, 143, 177)
SIZES = {"세로": (1080, 1920), "가로": (1280, 720)}
THUMB_FONT_URL = ("https://raw.githubusercontent.com/orioncactus/pretendard/main/packages/pretendard/"
                  "dist/public/static/Pretendard-ExtraBold.otf")


def thumb_font() -> Path:
    """썸네일은 더 굵은 글씨(Pretendard ExtraBold). 못 받으면 자막 폰트를 씁니다."""
    d = BASE_DIR / "fonts" / "thumb"
    for f in sorted(d.glob("*.otf")) + sorted(d.glob("*.ttf")):
        return f
    try:
        import requests
        r = requests.get(THUMB_FONT_URL, timeout=60)
        r.raise_for_status()
        d.mkdir(parents=True, exist_ok=True)
        (d / "Pretendard-ExtraBold.otf").write_bytes(r.content)
        return d / "Pretendard-ExtraBold.otf"
    except Exception:
        return edit.find_font(BASE_DIR / "fonts")


# ── 배경 장면 고르기 ─────────────────────────────────────
def _grab_frame(video: Path, out: Path) -> Path | None:
    try:
        t = edit.media_duration(video) * 0.5
        p = subprocess.run([edit.ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.2f}",
                            "-i", str(video), "-frames:v", "1", str(out)], capture_output=True)
        return out if p.returncode == 0 and out.exists() else None
    except edit.EditError:
        return None


def pick_background(out_dir: Path, ep: dict, work: Path) -> tuple[Image.Image | None, str]:
    clip_dir = out_dir / "clips" / f"EP{ep['no']:02d}"
    own = edit._find(clip_dir, "thumb", edit.IMAGE_EXT)
    if own:
        return Image.open(own).convert("RGB"), f"직접 고른 장면({own.name})"
    want = ep.get("thumbnail_cut") or 0
    order = sorted(ep["cuts"], key=lambda c: (c["no"] != want, -len(c["characters"]), c["no"]))
    for c in order:
        stem = f"cut{c['no']:02d}"
        video = edit._find(clip_dir, stem, edit.VIDEO_EXT)
        if video:
            work.mkdir(parents=True, exist_ok=True)
            frame = _grab_frame(video, work / f"thumb_{stem}.png")
            if frame:
                return Image.open(frame).convert("RGB"), f"컷 {c['no']} 영상"
        image = edit._find(clip_dir, stem, edit.IMAGE_EXT)
        if image:
            return Image.open(image).convert("RGB"), f"컷 {c['no']} 이미지"
    return None, "기본 배경(영상이 아직 없음)"


def _cover(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    w, h = size
    s = max(w / img.width, h / img.height)
    img = img.resize((max(w, round(img.width * s)), max(h, round(img.height * s))), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 3          # 얼굴이 위쪽에 오는 경우가 많아 위쪽을 더 남김
    return img.crop((x, y, x + w, y + h))


def _sunset(size: tuple[int, int]) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size)
    for y in range(h):
        k = y / h
        img.paste((int(255 - 120 * k), int(150 - 90 * k), int(170 - 60 * k)), (0, y, w, y + 1))
    return img


def _ramp(n: int, begin: float, strength: int) -> list[int]:
    """0..n-1 위치에서 begin(0~1) 이후로 점점 진해지는 값."""
    return [0 if i / (n - 1) < begin else int(strength * ((i / (n - 1) - begin) / (1 - begin)) ** 1.2)
            for i in range(n)]


def _shade(size: tuple[int, int], vertical: bool) -> Image.Image:
    """글자가 잘 보이도록 세로형은 아래쪽, 가로형은 왼쪽·아래쪽을 어둡게 합니다. 세로형은 맨 위도 살짝."""
    from PIL import ImageChops
    w, h = size
    down = Image.new("L", (1, 256))
    down.putdata(_ramp(256, 0.45 if vertical else 0.55, 225))
    mask = down.resize(size)
    if vertical:
        up = Image.new("L", (1, 256))
        up.putdata(list(reversed(_ramp(256, 0.85, 140))))
        mask = ImageChops.lighter(mask, up.resize(size))
    else:
        left = Image.new("L", (256, 1))
        left.putdata(list(reversed(_ramp(256, 0.35, 215))))
        mask = ImageChops.lighter(mask, left.resize(size))
    layer = Image.new("RGBA", size, (14, 8, 18, 0))
    layer.putalpha(mask)
    return layer


# ── 글자 ────────────────────────────────────────────────
def thumb_lines(ep: dict) -> list[str]:
    """썸네일 문구: 대본의 thumbnail_text → 없으면 회차 제목. 최대 2줄."""
    text = (ep.get("thumbnail_text") or ep["title"]).strip()
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if len(lines) == 1 and len(lines[0].replace(" ", "")) > 9:   # 한 줄이 길면 가운데 띄어쓰기에서 나눔
        words = lines[0].split(" ")
        if len(words) > 1:
            best = min(range(1, len(words)), key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
            lines = [" ".join(words[:best]), " ".join(words[best:])]
    return lines[:2]


def _fit(font_path: Path, lines: list[str], max_w: int, start: int) -> ImageFont.FreeTypeFont:
    size = start
    while size > 40:
        f = ImageFont.truetype(str(font_path), size)
        if max(f.getlength(l) for l in lines) <= max_w:
            return f
        size -= 4
    return ImageFont.truetype(str(font_path), size)


def _draw_text_block(img: Image.Image, lines: list[str], font: ImageFont.FreeTypeFont, x: int, y_bottom: int,
                     anchor_x: str, accent: tuple) -> int:
    """마지막 줄을 강조색으로. 그림자를 넣어 어떤 배경에서도 읽히게. 반환: 글자 블록의 위쪽 y."""
    lh = int(font.size * 1.16)
    top = y_bottom - lh * len(lines)
    txt = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(txt)
    a = "ma" if anchor_x == "center" else "la"
    for i, l in enumerate(lines):
        color = accent if (i == len(lines) - 1 and len(lines) > 1) else (255, 255, 255)
        d.text((x, top + i * lh), l, font=font, fill=color + (255,), anchor=a,
               stroke_width=max(3, font.size // 26), stroke_fill=(30, 12, 26, 255))
    blur = txt.getchannel("A").filter(ImageFilter.GaussianBlur(font.size // 6))
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow.putalpha(blur.point(lambda v: v * 200 // 255))
    img.alpha_composite(shadow)
    img.alpha_composite(txt)
    return top


def _pill(img: Image.Image, text: str, font: ImageFont.FreeTypeFont, x: int, y: int, fill: tuple,
          fg: tuple = (40, 20, 34)) -> int:
    d = ImageDraw.Draw(img)
    w, h = int(font.getlength(text)) + font.size, int(font.size * 1.55)
    d.rounded_rectangle((x, y, x + w, y + h), h // 2, fill=fill + (255,))
    d.text((x + w // 2, y + h // 2), text, font=font, fill=fg + (255,), anchor="mm")
    return w


def render(bg: Image.Image | None, series_title: str, ep: dict, font_path: Path, out: Path,
           kind: str = "세로", accent: tuple = PINK) -> Path:
    size = SIZES[kind]
    w, h = size
    base = _cover(bg, size) if bg else _sunset(size)
    base = ImageEnhance.Color(ImageEnhance.Contrast(base).enhance(1.08)).enhance(1.12)
    img = base.convert("RGBA")
    img.alpha_composite(_shade(size, vertical=(kind == "세로")))
    lines = thumb_lines(ep)
    small = ImageFont.truetype(str(font_path), 44 if kind == "세로" else 30)
    d = ImageDraw.Draw(img)
    if kind == "세로":
        d.text((w // 2, 120), series_title, font=small, fill=(255, 255, 255, 230), anchor="ma",
               stroke_width=2, stroke_fill=(30, 12, 26, 160))
        font = _fit(font_path, lines, w - 140, 150)
        top = _draw_text_block(img, lines, font, w // 2, 1520, "center", accent)
        ep_font = ImageFont.truetype(str(font_path), 40)
        tag = f"EP.{ep['no']:02d}"
        pw = int(ep_font.getlength(tag)) + ep_font.size
        _pill(img, tag, ep_font, (w - pw) // 2, top - 100, accent)
    else:
        pad = 64
        font = _fit(font_path, lines, int(w * 0.58), 112)
        top = _draw_text_block(img, lines, font, pad, h - 70, "left", accent)
        ep_font = ImageFont.truetype(str(font_path), 30)
        pw = _pill(img, f"EP.{ep['no']:02d}", ep_font, pad, top - 74, accent)
        d = ImageDraw.Draw(img)
        d.text((pad + pw + 18, top - 74 + int(ep_font.size * 0.78)), series_title, font=small,
               fill=(255, 255, 255, 235), anchor="lm", stroke_width=2, stroke_fill=(30, 12, 26, 160))
    img.convert("RGB").save(out, quality=92)
    return out


def make_thumbnails(out_dir: Path, series: dict, ep_no: int, cfg: dict | None = None, log=print) -> list[Path]:
    ep = next((e for e in series["episodes"] if e["no"] == ep_no), None)
    if not ep:
        raise edit.EditError(f"EP{ep_no:02d} 가 series.json 에 없어요.")
    tag = f"EP{ep_no:02d}"
    bg, where = pick_background(out_dir, ep, out_dir / "_편집작업" / tag)
    color = (cfg or {}).get("edit", {}).get("thumbnail_color") or "#FF8FB1"
    accent = subtitle_style._hex(color)[:3]
    font = thumb_font()
    files = [render(bg, series["bible"]["title"], ep, font, out_dir / f"06_썸네일_{tag}_{k}.jpg", k, accent)
             for k in SIZES]
    log(f"  · 썸네일 배경: {where}  /  문구: {' / '.join(thumb_lines(ep))}")
    return files
