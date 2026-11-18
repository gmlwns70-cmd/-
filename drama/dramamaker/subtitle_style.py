"""자막 디자인. 투명 PNG(1080x1920) 한 장에 자막 한 줄 묶음을 그립니다.

스타일
  romance : 반투명 둥근 상자 + 말하는 사람 이름표(인물별 색) — 로맨스 숏드라마 기본
  minimal : 상자 없이 흰 글자 + 부드러운 그림자
  outline : 흰 글자 + 검은 테두리 (예능/클래식)
"""
from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1920
BOTTOM = 1560          # 자막 아래 끝 위치. 쇼츠·릴스 하단 버튼에 가리지 않는 높이
MAX_W = 860            # 한 줄 최대 폭(px)
STYLES = ("romance", "minimal", "outline")

FEMALE_COLORS = ["#FF8FB1", "#FFB86B", "#F7A8E0"]   # 핑크, 피치, 라일락핑크
MALE_COLORS = ["#7FB8FF", "#8FE3C8", "#B9A6FF"]     # 하늘, 민트, 라벤더


def is_male(c: dict) -> bool:
    text = c.get("voice", "") + " " + c.get("look_en", "")
    return bool(re.search(r"남(성|자)|\bmale\b|\bman\b", text, re.I)) and \
        not re.search(r"여(성|자)|female|woman", c.get("voice", ""))


def char_colors(bible: dict, overrides: dict | None = None) -> dict:
    """인물별 이름표 색. 여자 인물은 따뜻한 색, 남자 인물은 시원한 색으로 차례대로 고릅니다."""
    out, n = {}, {"m": 0, "f": 0}
    for c in bible["characters"]:
        g = "m" if is_male(c) else "f"
        pal = MALE_COLORS if g == "m" else FEMALE_COLORS
        out[c["id"]] = (overrides or {}).get(c["id"]) or pal[n[g] % len(pal)]
        n[g] += 1
    return out


def _hex(color: str, alpha: int = 255) -> tuple:
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4)) + (alpha,)


def wrap_px(text: str, font: ImageFont.FreeTypeFont, max_w: int = MAX_W) -> list[str]:
    """글자 폭을 실제로 재서 줄을 나눕니다. 띄어쓰기 단위로 끊고, 너무 긴 단어만 글자 단위로 끊습니다."""
    lines = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split(" "):
            trial = f"{cur} {word}".strip()
            if font.getlength(trial) <= max_w:
                cur = trial
                continue
            if cur:
                lines.append(cur)
            cur = ""
            for ch in word:
                if font.getlength(cur + ch) > max_w and cur:
                    lines.append(cur)
                    cur = ""
                cur += ch
        lines.append(cur)
    return [l for l in lines if l] or [""]


def balanced_wrap(text: str, font: ImageFont.FreeTypeFont, max_w: int = MAX_W) -> list[str]:
    """줄 수는 그대로 두고 폭을 줄여 가며, 줄 길이가 고르게 되는 나눔을 찾습니다."""
    lines = wrap_px(text, font, max_w)
    if len(lines) < 2:
        return lines
    best, w = lines, max_w
    while w > 200:
        w -= 20
        trial = wrap_px(text, font, w)
        if len(trial) > len(lines):
            break
        best = trial
    return best


def _soft_shadow(layer: Image.Image, radius: int, alpha: int) -> Image.Image:
    a = layer.getchannel("A").filter(ImageFilter.GaussianBlur(radius))
    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    shadow.putalpha(a.point(lambda v: v * alpha // 255))
    return shadow


def render(text: str, font_path: Path, out: Path, style: str = "romance", size: int = 58,
           speaker: str = "", color: str = "#FF8FB1") -> None:
    font = ImageFont.truetype(str(font_path), size)
    lines = balanced_wrap(text, font)
    line_h = int(size * 1.38)
    widths = [font.getlength(l) for l in lines]
    text_h = line_h * len(lines)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    if style == "outline":
        d = ImageDraw.Draw(img)
        top = BOTTOM - text_h
        for i, l in enumerate(lines):
            d.text((W // 2, top + i * line_h), l, font=font, fill="white", anchor="ma",
                   stroke_width=max(4, size // 11), stroke_fill="black")
        img.save(out)
        return

    if style == "minimal":
        txt = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(txt)
        top = BOTTOM - text_h
        for i, l in enumerate(lines):
            d.text((W // 2, top + i * line_h), l, font=font, fill="white", anchor="ma")
        img = Image.alpha_composite(img, _soft_shadow(txt, 10, 230))
        img = Image.alpha_composite(img, _soft_shadow(txt, 3, 200))
        img = Image.alpha_composite(img, txt)
        img.save(out)
        return

    # romance: 반투명 둥근 상자 + 이름표
    pad_x, pad_y = int(size * 0.62), int(size * 0.42)
    box_w = int(max(widths)) + 2 * pad_x
    box_h = text_h - (line_h - size) + 2 * pad_y + int(size * 0.12)
    x0, y1 = (W - box_w) // 2, BOTTOM
    y0 = y1 - box_h
    radius = int(size * 0.55)

    box = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(box).rounded_rectangle((x0, y0, x0 + box_w, y1), radius, fill=(22, 16, 26, 168))
    shadow = _soft_shadow(box, 22, 120)
    img = Image.alpha_composite(img, shadow.transform(img.size, Image.AFFINE, (1, 0, 0, 0, 1, -6)))
    img = Image.alpha_composite(img, box)
    d = ImageDraw.Draw(img)

    for i, l in enumerate(lines):
        d.text((W // 2, y0 + pad_y + i * line_h), l, font=font, fill=(255, 255, 255, 255), anchor="ma")

    if speaker:
        nf = ImageFont.truetype(str(font_path), int(size * 0.5))
        nw = int(nf.getlength(speaker))
        cw, ch = nw + int(size * 0.7), int(size * 0.82)
        cx0, cy1 = x0 + int(size * 0.3), y0 + int(ch * 0.35)
        cy0 = cy1 - ch
        chip = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(chip).rounded_rectangle((cx0, cy0, cx0 + cw, cy1), ch // 2, fill=_hex(color))
        img = Image.alpha_composite(img, _soft_shadow(chip, 8, 110))
        img = Image.alpha_composite(img, chip)
        ImageDraw.Draw(img).text((cx0 + cw // 2, (cy0 + cy1) // 2), speaker, font=nf,
                                 fill=(40, 26, 38, 255), anchor="mm")
    img.save(out)


def preview(font_path: Path, out: Path, size: int = 58) -> Path:
    """세 가지 스타일을 한 장에 모아 미리보기 이미지를 만듭니다."""
    bg = Image.new("RGB", (W, H))
    for y in range(H):  # 노을빛 배경
        bg.paste((int(60 + 120 * y / H), int(70 + 50 * y / H), int(110 - 40 * y / H)), (0, y, W, y + 1))
    items = [("romance", "그 우산, 제 건데요.", "한하은", FEMALE_COLORS[0]),
             ("romance", "내일도 비 온다던데. 그럼 우산 하나 더 챙겨 와요, 같이 쓰게.", "강도준", MALE_COLORS[0]),
             ("minimal", "그 우산, 제 건데요.", "", FEMALE_COLORS[0]),
             ("outline", "그 우산, 제 건데요.", "", FEMALE_COLORS[0])]
    sheet = Image.new("RGB", (1090, 700), "white")
    label = ImageFont.truetype(str(font_path), 26)
    for i, (style, text, who, color) in enumerate(items):
        tmp = out.with_name(f"_preview_{i}.png")
        render(text, font_path, tmp, style, size, who, color)
        tile = bg.copy().convert("RGBA")
        tile.alpha_composite(Image.open(tmp))
        tmp.unlink()
        x, y = (i % 2) * 550, (i // 2) * 350
        sheet.paste(tile.convert("RGB").crop((0, 1100, W, 1700)).resize((540, 300)), (x, y + 40))
        ImageDraw.Draw(sheet).text((x + 8, y + 6), f"subtitle_style: {style}", font=label, fill=(60, 60, 60))
    sheet.save(out)
    return out
