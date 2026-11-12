"""Pillow로 카드 한 장 한 장을 합성합니다.

레이아웃
- cover       : 제목은 위 25%에 크게, 일러스트는 아래 70%
- illustrated : 일러스트는 위 65%, 글은 아래 35%
- text        : 글을 화면 가운데에 세로 정렬
일러스트 파일이 없으면(텍스트 카드 전용 모드) cover 는 '제목만 있는 표지',
illustrated 는 text 레이아웃으로 자동 전환됩니다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from . import fonts, paper

W, H = 1080, 1350
TEXT_COLOR = (0x2B, 0x2B, 0x2B)
HL_COLOR = (0xF3, 0xE0, 0x7A)
HL_PAD_X = 12
SIDE = 90                      # 좌우 여백
MAX_W = W - SIDE * 2           # 글 최대 폭 900px
SHADOW_OFFSET = 3
SHADOW_BLUR = 4
SHADOW_ALPHA = 0.33

# 영역 (left, top, right, bottom)
COVER_TITLE_BOX = (SIDE, 70, W - SIDE, int(H * 0.25))
COVER_IMAGE_BOX = (40, int(H * 0.30), W - 40, H)
ILL_IMAGE_BOX = (60, 40, W - 60, int(H * 0.65))
ILL_TEXT_BOX = (SIDE, int(H * 0.65) + 24, W - SIDE, H - 70)
TEXT_BOX = (SIDE, 150, W - SIDE, H - 150)


@dataclass
class CardResult:
    image: Image.Image
    layout: str
    font_size: int
    text_box: tuple | None = None          # 실제로 글이 그려진 영역
    figure_box: tuple | None = None        # 일러스트에서 인물/소품이 있는 영역(대략)
    warnings: list = field(default_factory=list)


class Renderer:
    def __init__(self, style: dict, brand: str = ""):
        self.style = style
        self.brand = brand
        self.font_path = str(fonts.ensure_font())
        self.paper = paper.get_paper()
        self._fonts: dict[int, ImageFont.FreeTypeFont] = {}

    # ── 폰트/측정 ─────────────────────────────────────────
    def font(self, size: int) -> ImageFont.FreeTypeFont:
        if size not in self._fonts:
            self._fonts[size] = ImageFont.truetype(self.font_path, size)
        return self._fonts[size]

    def text_w(self, text: str, size: int) -> int:
        return int(self.font(size).getlength(text))

    def _wrap_word(self, text: str, size: int, max_w: int) -> list[str]:
        """한 줄이 너무 길면 어절(띄어쓰기) 단위로만 나눕니다. 단어 중간에서 끊지 않습니다."""
        if self.text_w(text, size) <= max_w:
            return [text]
        words, lines, cur = text.split(" "), [], ""
        for w in words:
            cand = f"{cur} {w}".strip()
            if cur and self.text_w(cand, size) > max_w:
                lines.append(cur)
                cur = w
            else:
                cur = cand
        if cur:
            lines.append(cur)
        return lines

    def fit(self, lines: list[dict], box: tuple, start: int) -> tuple[int, list[dict], list[str]]:
        """글이 상자에 들어갈 때까지 글자 크기를 2px씩 줄입니다(최소 min_size)."""
        min_size = int(self.style["min_size"])
        lh = float(self.style["line_height"])
        bw, bh = box[2] - box[0], box[3] - box[1]
        warnings = []
        size = start
        while True:
            fits_w = all(self.text_w(l["text"], size) <= bw for l in lines)
            fits_h = len(lines) * size * lh <= bh
            if (fits_w and fits_h) or size <= min_size:
                break
            size = max(min_size, size - 2)
        out = lines
        if not all(self.text_w(l["text"], size) <= bw for l in lines):
            out = []
            for l in lines:
                for part in self._wrap_word(l["text"], size, bw):
                    out.append({"text": part, "highlight": l.get("highlight", False)})
            warnings.append(f"글자가 넘쳐서 최소 크기 {size}px에서 어절 단위로 줄을 다시 나눴어요")
        if len(out) * size * lh > bh:
            warnings.append(f"최소 크기 {size}px에서도 글이 영역 높이를 넘어요 → 원고 줄 수를 줄여 주세요")
        return size, out, warnings

    # ── 그리기 ───────────────────────────────────────────
    def draw_block(self, canvas: Image.Image, lines: list[dict], box: tuple, size: int) -> tuple:
        """글 덩어리를 상자 가운데에 그립니다: 형광펜 → 그림자 → 글자 순서."""
        lh = size * float(self.style["line_height"])
        total = lh * len(lines)
        top = box[1] + (box[3] - box[1] - total) / 2
        cx = (box[0] + box[2]) / 2
        font = self.font(size)

        hl_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        hl_draw = ImageDraw.Draw(hl_layer)
        mask = Image.new("L", canvas.size, 0)
        mask_draw = ImageDraw.Draw(mask)
        minx, miny, maxx, maxy = W, H, 0, 0

        for i, line in enumerate(lines):
            text = line["text"]
            cy = top + lh * i + lh / 2
            if not text:
                continue
            l, t, r, b = mask_draw.textbbox((cx, cy), text, font=font, anchor="mm")
            if line.get("highlight") and text.strip():
                pad_y = max(4, int(size * 0.08))
                hl_draw.rectangle((l - HL_PAD_X, t - pad_y, r + HL_PAD_X, b + pad_y), fill=HL_COLOR + (235,))
            mask_draw.text((cx, cy), text, font=font, fill=255, anchor="mm")
            minx, miny, maxx, maxy = min(minx, l - HL_PAD_X), min(miny, t), max(maxx, r + HL_PAD_X), max(maxy, b)

        base = canvas.convert("RGBA")
        base = Image.alpha_composite(base, hl_layer)

        # 그림자: 아래로 3px, 흐림 4px, 반투명 검정 → 종이에 눌린 느낌
        shadow_mask = Image.new("L", canvas.size, 0)
        shadow_mask.paste(mask, (0, SHADOW_OFFSET))
        shadow_mask = shadow_mask.filter(ImageFilter.GaussianBlur(SHADOW_BLUR))
        shadow_mask = shadow_mask.point(lambda v: int(v * SHADOW_ALPHA))
        base.paste(Image.new("RGBA", canvas.size, (0, 0, 0, 255)), (0, 0), shadow_mask)

        base.paste(Image.new("RGBA", canvas.size, TEXT_COLOR + (255,)), (0, 0), mask)
        canvas.paste(base.convert("RGB"))
        return (int(minx), int(miny), int(maxx), int(maxy))

    def draw_page_pill(self, canvas: Image.Image, idx: int, total: int) -> None:
        label = f"{idx}/{total}"
        font = self.font(30)
        tw = font.getlength(label)
        pw, ph = int(tw + 40), 54
        x1, y1 = W - 48, 48
        x0, y0 = x1 - pw, y1 - 0
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        d.rounded_rectangle((x0, y0, x1, y0 + ph), radius=ph // 2, fill=(55, 55, 55, 175))
        d.text(((x0 + x1) / 2, y0 + ph / 2), label, font=font, fill=(255, 255, 255, 255), anchor="mm")
        canvas.paste(Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB"))

    def draw_brand(self, canvas: Image.Image, y: int) -> None:
        if not self.brand:
            return
        d = ImageDraw.Draw(canvas)
        d.text((W / 2, y), self.brand, font=self.font(30), fill=(105, 105, 105), anchor="mm")

    def place_illustration(self, canvas: Image.Image, img_path: Path, box: tuple, align: str = "center") -> tuple | None:
        """일러스트를 상자 안에 맞춰 넣고, 곱하기 합성 + 가장자리 페이드로 종이에 스며들게 합니다.
        반환값: 인물/소품이 실제로 그려진 대략의 영역(겹침 검사용)."""
        src = Image.open(img_path).convert("RGBA")
        white = Image.new("RGBA", src.size, (255, 255, 255, 255))
        rgb = Image.alpha_composite(white, src).convert("RGB")
        alpha = src.getchannel("A")

        bw, bh = box[2] - box[0], box[3] - box[1]
        scale = min(bw / src.width, bh / src.height)
        nw, nh = int(src.width * scale), int(src.height * scale)
        rgb = rgb.resize((nw, nh), Image.LANCZOS)
        alpha = alpha.resize((nw, nh), Image.LANCZOS)
        x = box[0] + (bw - nw) // 2
        y = box[1] + (bh - nh) if align == "bottom" else box[1] + (bh - nh) // 2

        # 가장자리 페이드 마스크
        feather = max(24, int(min(nw, nh) * 0.06))
        edge = Image.new("L", (nw, nh), 0)
        ImageDraw.Draw(edge).rectangle((feather, feather, nw - feather, nh - feather), fill=255)
        edge = edge.filter(ImageFilter.GaussianBlur(feather * 0.6))
        mask = ImageChops.multiply(edge, alpha)

        region = canvas.crop((x, y, x + nw, y + nh))
        blended = ImageChops.multiply(region, rgb)   # 흰 배경은 종이색이 그대로 비침
        canvas.paste(blended, (x, y), mask)

        # 인물 영역 추정: 충분히 어둡고 마스크가 살아 있는 픽셀
        lum = np.asarray(rgb.convert("L"), dtype=np.int16)
        m = np.asarray(mask, dtype=np.int16)
        ys, xs = np.nonzero((lum < 225) & (m > 90))
        if len(xs) < 50:
            return None
        return (int(x + xs.min()), int(y + ys.min()), int(x + xs.max()), int(y + ys.max()))

    # ── 카드 한 장 ───────────────────────────────────────
    def render_card(self, card: dict, idx: int, total: int, image_path: Path | None) -> CardResult:
        canvas = self.paper.copy()
        lines = [dict(l, text=str(l.get("text", "")).strip()) for l in card.get("lines", [])]
        while lines and not lines[0]["text"]:
            lines.pop(0)
        while lines and not lines[-1]["text"]:
            lines.pop()   # 가운데 빈 줄은 문장 덩어리 사이 간격으로 씁니다
        ctype = card.get("type", "text")
        has_img = bool(image_path and Path(image_path).exists())
        st = self.style

        if ctype == "cover":
            if has_img:
                fig = self.place_illustration(canvas, image_path, COVER_IMAGE_BOX, align="bottom")
                size, lines, warns = self.fit(lines, COVER_TITLE_BOX, int(st["cover_size"]))
                tb = self.draw_block(canvas, lines, COVER_TITLE_BOX, size)
                self.draw_brand(canvas, 40)
                return CardResult(canvas, "cover", size, tb, fig, warns)
            box = (SIDE, 200, W - SIDE, H - 260)
            size, lines, warns = self.fit(lines, box, int(st["cover_size"]) + 8)
            tb = self.draw_block(canvas, lines, box, size)
            self.draw_brand(canvas, H - 120)
            return CardResult(canvas, "cover(텍스트 전용)", size, tb, None, warns)

        if ctype == "illustrated" and has_img:
            fig = self.place_illustration(canvas, image_path, ILL_IMAGE_BOX, align="bottom")
            size, lines, warns = self.fit(lines, ILL_TEXT_BOX, int(st["illustrated_size"]))
            tb = self.draw_block(canvas, lines, ILL_TEXT_BOX, size)
            self.draw_page_pill(canvas, idx, total)
            return CardResult(canvas, "illustrated", size, tb, fig, warns)

        size, lines, warns = self.fit(lines, TEXT_BOX, int(st["text_size"]))
        tb = self.draw_block(canvas, lines, TEXT_BOX, size)
        self.draw_page_pill(canvas, idx, total)
        layout = "text" if ctype == "text" else "text(일러스트 없음)"
        return CardResult(canvas, layout, size, tb, None, warns)


def render_dir(out_dir: Path, cfg: dict, only: list[int] | None = None) -> list[dict]:
    """output 폴더의 script.json 을 읽어 card_XX.png 를 다시 만듭니다. 이미지는 새로 생성하지 않습니다."""
    out_dir = Path(out_dir)
    script = json.loads((out_dir / "script.json").read_text(encoding="utf-8"))
    cards = script["cards"]
    total = int(script.get("total_cards") or len(cards))
    renderer = Renderer(cfg["style"], script.get("brand") or cfg.get("brand", ""))

    if only is None:  # 장수가 줄었으면 남은 옛 파일 정리
        for old in out_dir.glob("card_*.png"):
            try:
                if int(old.stem.split("_")[1]) > len(cards):
                    old.unlink()
            except ValueError:
                pass

    meta = []
    for i, card in enumerate(cards, start=1):
        no = int(card.get("no", i))
        if only and no not in only:
            continue
        img = out_dir / "images" / f"card_{no:02d}.png"
        res = renderer.render_card(card, no, total, img if img.exists() else None)
        res.image.save(out_dir / f"card_{no:02d}.png", optimize=True)
        for w in res.warnings:
            print(f"  ⚠ {no}번 카드: {w}")
        meta.append({
            "no": no, "layout": res.layout, "font_size": res.font_size,
            "text_box": res.text_box, "figure_box": res.figure_box, "warnings": res.warnings,
        })
        print(f"  ✓ card_{no:02d}.png  ({res.layout}, {res.font_size}px)")
    (out_dir / "render_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta
