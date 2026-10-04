"""5단계: 자막 (줄바꿈, 타이밍, SRT, 스타일이 적용된 글자 이미지)."""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable

from PIL import Image, ImageColor, ImageDraw, ImageFont

from .config import FONTS_DIR, ROOT, UserFacingError, load_config
from .project import Project

# ---------------- 폰트 ----------------
FONT_PREFERENCE = ["pretendard-bold", "pretendard-extrabold", "pretendard-semibold", "nanumsquareeb",
                   "nanumsquareb", "nanumsquare_acb", "nanumsquareneo-dheavy", "nanumsquareneo-cbd",
                   "pretendard", "nanumsquare"]
SYSTEM_FONTS = [
    "C:/Windows/Fonts/malgunbd.ttf", "C:/Windows/Fonts/malgun.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]


def find_font(font_file: str = "", fonts_dir: Path = FONTS_DIR) -> Path | None:
    """fonts 폴더 → 시스템 한글 폰트 순서로 찾습니다."""
    if font_file:
        p = Path(font_file)
        p = p if p.is_absolute() else ROOT / p
        if p.exists():
            return p
    if fonts_dir.exists():
        files = [p for p in fonts_dir.rglob("*") if p.suffix.lower() in (".ttf", ".otf", ".ttc")]
        for pref in FONT_PREFERENCE:
            for p in files:
                if p.stem.lower().replace(" ", "").startswith(pref):
                    return p
        if files:
            return sorted(files)[0]
    for s in SYSTEM_FONTS:
        if Path(s).exists():
            return Path(s)
    return None


@lru_cache(maxsize=32)
def _load_font(path: str | None, size: int):
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


@dataclass
class SubtitleStyle:
    font_path: str | None = None
    font_size: int = 54
    stroke_width: int = 4
    color: str = "#FFFFFF"
    stroke_color: str = "#000000"
    bottom_margin_pct: float = 10
    max_chars_per_line: int = 18
    max_lines: int = 2
    line_spacing: float = 1.25
    box_color: str | None = None   # 예: "#000000AA" → 반투명 상자

    @classmethod
    def from_config(cls, cfg: dict | None = None, **override) -> "SubtitleStyle":
        s = {**(cfg or load_config())["subtitles"], **override}
        font = find_font(s.get("font_file", ""))
        return cls(font_path=str(font) if font else None, font_size=int(s["font_size"]),
                   stroke_width=int(s["stroke_width"]), color=s["color"], stroke_color=s["stroke_color"],
                   bottom_margin_pct=float(s["bottom_margin_pct"]),
                   max_chars_per_line=int(s["max_chars_per_line"]), max_lines=int(s["max_lines"]),
                   box_color=s.get("box_color"))

    def scaled(self, factor: float) -> "SubtitleStyle":
        from dataclasses import replace
        return replace(self, font_size=max(10, round(self.font_size * factor)),
                       stroke_width=max(1, round(self.stroke_width * factor)) if self.stroke_width else 0)


def render_text_image(text: str, style: SubtitleStyle, max_width: int | None = None) -> Image.Image:
    """테두리가 있는 글자를 투명 배경 PNG(RGBA) 이미지로 만듭니다."""
    font = _load_font(style.font_path, style.font_size)
    lines = text.split("\n")
    sw = style.stroke_width
    dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    boxes = [dummy.textbbox((0, 0), ln or " ", font=font, stroke_width=sw) for ln in lines]
    line_h = int(style.font_size * style.line_spacing)
    width = max(b[2] - b[0] for b in boxes) + 2 * sw + 8
    if max_width:
        width = min(width, max_width)
    pad = int(style.font_size * 0.35) if style.box_color else 0
    height = line_h * (len(lines) - 1) + (boxes[-1][3] - min(0, boxes[-1][1])) + 2 * sw + 8
    img = Image.new("RGBA", (width + 2 * pad, height + 2 * pad), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if style.box_color:
        draw.rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=pad,
                               fill=ImageColor.getrgb(style.box_color))
    y = pad + sw + 4
    for ln, b in zip(lines, boxes):
        w = b[2] - b[0]
        x = (img.width - w) // 2 - b[0]
        draw.text((x, y - min(0, b[1])), ln, font=font, fill=style.color,
                  stroke_width=sw, stroke_fill=style.stroke_color)
        y += line_h
    return img


# ---------------- 줄바꿈 ----------------
def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。…~])\s+|\n+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def wrap_lines(text: str, max_chars: int = 18) -> list[str]:
    """어절(띄어쓰기) 단위로 한 줄 최대 max_chars 글자가 되게 나눕니다."""
    lines: list[str] = []
    cur = ""
    for word in text.split():
        while len(word) > max_chars:          # 너무 긴 단어는 강제로 자름
            if cur:
                lines.append(cur)
                cur = ""
            lines.append(word[:max_chars])
            word = word[max_chars:]
        if not cur:
            cur = word
        elif len(cur) + 1 + len(word) <= max_chars:
            cur += " " + word
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _balance(lines: list[str], max_chars: int) -> list[str]:
    """마지막 줄이 너무 짧으면(예: 1~2글자) 앞 줄과 균형을 맞춥니다."""
    if len(lines) >= 2 and len(lines[-1]) <= 3:
        merged = lines[-2] + " " + lines[-1]
        words = merged.split()
        best = None
        for i in range(1, len(words)):
            a, b = " ".join(words[:i]), " ".join(words[i:])
            if len(a) <= max_chars and len(b) <= max_chars:
                diff = abs(len(a) - len(b))
                if best is None or diff < best[0]:
                    best = (diff, a, b)
        if best:
            lines = lines[:-2] + [best[1], best[2]]
    return lines


def chunk_text(text: str, max_chars: int = 18, max_lines: int = 2) -> list[str]:
    """화면에 한 번에 보여줄 자막 조각(1~max_lines줄) 목록."""
    chunks: list[str] = []
    for sent in split_sentences(text):
        lines = wrap_lines(sent, max_chars)
        groups = [lines[i:i + max_lines] for i in range(0, len(lines), max_lines)]
        for g in groups:
            chunks.append("\n".join(_balance(g, max_chars)))
    return chunks


# ---------------- 타이밍 ----------------
def scene_timeline(scenes: list[dict], padding: float) -> list[tuple[float, float]]:
    """각 장면의 (시작, 길이). 렌더링과 자막이 같은 기준을 쓰도록 여기 한 곳에서 계산합니다."""
    out, t = [], 0.0
    for sc in scenes:
        length = float(sc.get("duration") or 2.0) + padding
        out.append((t, length))
        t += length
    return out


def _distribute(chunks: list[str], start: float, end: float) -> list[dict]:
    weights = [max(1, len(c.replace("\n", "").replace(" ", ""))) for c in chunks]
    total = sum(weights)
    cues, t = [], start
    for c, w in zip(chunks, weights):
        d = (end - start) * w / total
        cues.append({"start": round(t, 3), "end": round(t + d, 3), "text": c})
        t += d
    return cues


def scene_cues(scene: dict, max_chars: int = 18, max_lines: int = 2) -> list[dict]:
    """장면 안에서의 자막 (장면 시작 = 0초 기준)."""
    text = scene.get("narration", "").strip()
    duration = float(scene.get("duration") or 0)
    if not text or duration <= 0:
        return []
    words = scene.get("words")  # faster-whisper 정렬 결과
    if words:
        return _cues_from_words(chunk_text(text, max_chars, max_lines), words, duration)
    sentences = scene.get("sentences") or []
    if sentences:
        cues = []
        for i, s in enumerate(sentences):
            end = sentences[i + 1]["start"] if i + 1 < len(sentences) else max(s["end"], duration)
            cues += _distribute(chunk_text(s["text"], max_chars, max_lines) or [s["text"]], s["start"], min(end, duration))
        return cues
    return _distribute(chunk_text(text, max_chars, max_lines), 0.0, duration)


def _cues_from_words(chunks: list[str], words: list[dict], duration: float) -> list[dict]:
    """whisper 단어 타이밍에 글자 수 위치를 맞춰 각 자막 조각의 시작 시간을 정합니다."""
    marks, pos = [], 0
    for w in words:
        n = len(re.sub(r"\s", "", w["word"]))
        marks.append((pos, w["start"], w["end"]))
        pos += n
    total_w = max(pos, 1)
    sizes = [len(re.sub(r"\s", "", c)) for c in chunks]
    total_c = max(sum(sizes), 1)

    def time_at(char_pos: float) -> float:
        target = char_pos * total_w / total_c
        for p, s, _ in reversed(marks):
            if p <= target:
                return s
        return 0.0

    cues, acc = [], 0
    starts = []
    for n in sizes:
        starts.append(time_at(acc))
        acc += n
    for i, c in enumerate(chunks):
        end = starts[i + 1] if i + 1 < len(chunks) else min(duration, marks[-1][2] + 0.3)
        cues.append({"start": round(starts[i], 3), "end": round(max(end, starts[i] + 0.3), 3), "text": c})
    return cues


def align_with_whisper(project: Project, model_size: str = "small",
                       progress: Callable[[float, str], None] | None = None) -> None:
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise UserFacingError("❌ 정밀 정렬에는 faster-whisper가 필요해요.\n"
                              "명령 프롬프트에서 `.venv\\Scripts\\pip install faster-whisper` 를 실행한 뒤 다시 시도해 주세요.") from e
    data = project.load_scenes()
    model = WhisperModel(model_size, device="auto", compute_type="int8")
    for i, sc in enumerate(data["scenes"]):
        if progress:
            progress(i / len(data["scenes"]), f"장면 {sc['id']} 음성 분석 중…")
        if not sc.get("audio"):
            continue
        segments, _ = model.transcribe(str(project.path / sc["audio"]), language="ko", word_timestamps=True)
        sc["words"] = [{"word": w.word, "start": w.start, "end": w.end} for seg in segments for w in (seg.words or [])]
    project.save_scenes(data)


def all_cues(scenes: list[dict], padding: float, max_chars: int = 18, max_lines: int = 2) -> list[dict]:
    cues = []
    for sc, (start, _) in zip(scenes, scene_timeline(scenes, padding)):
        for c in scene_cues(sc, max_chars, max_lines):
            cues.append({**c, "start": c["start"] + start, "end": c["end"] + start})
    return cues


def fmt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(cues: list[dict]) -> str:
    blocks = [f"{i}\n{fmt_time(c['start'])} --> {fmt_time(c['end'])}\n{c['text']}\n"
              for i, c in enumerate(cues, start=1)]
    return "\n".join(blocks)


def build_subtitles(project: Project, max_chars: int | None = None, max_lines: int | None = None,
                    use_whisper: bool = False, whisper_model: str = "small",
                    progress: Callable[[float, str], None] | None = None, cfg: dict | None = None) -> list[dict]:
    cfg = cfg or load_config()
    data = project.load_scenes()
    if not data:
        raise UserFacingError("❌ 내레이션 정보가 없어요. ③ 내레이션 단계를 먼저 실행해 주세요.")
    project.invalidate_from("subtitles")
    if use_whisper:
        align_with_whisper(project, whisper_model, progress)
        data = project.load_scenes()
    else:
        for sc in data["scenes"]:
            sc.pop("words", None)
        project.save_scenes(data)
    max_chars = max_chars or int(cfg["subtitles"]["max_chars_per_line"])
    max_lines = max_lines or int(cfg["subtitles"]["max_lines"])
    cues = all_cues(data["scenes"], float(cfg["render"]["scene_padding"]), max_chars, max_lines)
    project.srt_path.write_text(to_srt(cues), encoding="utf-8")
    project.update_settings(sub_max_chars=max_chars, sub_max_lines=max_lines)
    project.mark_done("subtitles", cues=len(cues))
    return cues


def font_warning() -> str | None:
    if find_font(load_config()["subtitles"].get("font_file", "")) is None:
        hint = "fonts 폴더에 Pretendard 또는 나눔스퀘어 폰트를 넣어 주세요." if sys.platform != "win32" else \
            "fonts 폴더에 Pretendard 또는 나눔스퀘어 폰트를 넣어 주세요. (맑은 고딕도 찾지 못했어요)"
        return f"⚠️ 한글 폰트를 찾지 못했어요. 자막이 깨질 수 있어요. {hint}"
    return None
