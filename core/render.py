"""6단계: 영상 조립 (moviepy 2.x + ffmpeg).

장면 순서대로 [소재 영상/사진 + 내레이션 + 자막 + 화면 텍스트]를 합치고,
배경음악은 말하는 구간에서 자동으로 볼륨을 낮춥니다(덕킹).
"""
from __future__ import annotations

import os
import random
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageFilter
from proglog import ProgressBarLogger

from .assets import resolve_path
from .config import BGM_DIR, UserFacingError, find_ffmpeg, load_config
from .project import Project
from .subtitles import SubtitleStyle, render_text_image, scene_cues, scene_timeline

LANDSCAPE = (1920, 1080)
PORTRAIT = (1080, 1920)
QUALITY = {"1080p": 1.0, "720p": 2 / 3, "480p": 4 / 9}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}


def list_bgm(folder: Path = BGM_DIR) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in AUDIO_EXT)


# ---------------- 진행률 ----------------
class CallbackLogger(ProgressBarLogger):
    """moviepy 진행률을 0~1 숫자로 바꿔 콜백으로 전달 (Streamlit 진행 막대용)."""

    def __init__(self, callback: Callable[[float, str], None] | None, start: float = 0.0, end: float = 1.0):
        super().__init__()
        self.cb, self.start, self.end = callback, start, end

    def bars_callback(self, bar, attr, value, old_value=None):
        if not self.cb or attr != "index":
            return
        total = self.bars[bar].get("total") or 1
        frac = value / total
        if bar == "chunk":      # 오디오 합치기 (전체의 앞 5%)
            p, msg = 0.05 * frac, "오디오 합치는 중…"
        else:                   # 영상 프레임 쓰기
            p, msg = 0.05 + 0.95 * frac, f"영상 만드는 중… {int(frac * 100)}%"
        self.cb(self.start + (self.end - self.start) * p, msg)


# ---------------- 이미지/영상 맞추기 ----------------
def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    scale = max(w / img.width, h / img.height)
    nw, nh = max(w, round(img.width * scale)), max(h, round(img.height * scale))
    img = img.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - w) // 2, (nh - h) // 2
    return img.crop((left, top, left + w, top + h))


def blurred_background(frame: Image.Image, w: int, h: int) -> np.ndarray:
    bg = _cover(frame.convert("RGB"), w, h).filter(ImageFilter.GaussianBlur(radius=max(8, w // 40)))
    return (np.asarray(bg).astype(np.float32) * 0.55).astype(np.uint8)


def ken_burns_clip(path: Path, duration: float, w: int, h: int, seed: int = 0):
    """사진을 천천히 확대/이동하는 영상으로 만듭니다."""
    from moviepy import VideoClip

    zoom = 1.15
    bw, bh = round(w * zoom), round(h * zoom)
    big = _cover(Image.open(path).convert("RGB"), bw, bh)
    rnd = random.Random(seed)
    zoom_in = rnd.random() < 0.6
    dx = rnd.choice([-1, 0, 1])
    dy = rnd.choice([-1, 0, 1]) if dx == 0 else 0

    def frame(t):
        p = min(max(t / duration, 0.0), 1.0) if duration > 0 else 0.0
        p = p * p * (3 - 2 * p)                      # 부드러운 가속/감속
        z = 1 + (zoom - 1) * (p if zoom_in else 1 - p)
        cw, ch = bw / z, bh / z
        max_dx, max_dy = (bw - cw) / 2, (bh - ch) / 2
        pan = (p - 0.5) * 2                          # -1 → 1
        cx = bw / 2 + dx * pan * max_dx
        cy = bh / 2 + dy * pan * max_dy
        box = (cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)
        return np.asarray(big.resize((w, h), Image.BILINEAR, box=box))

    return VideoClip(frame, duration=duration)


def fit_video(clip, w: int, h: int):
    """영상을 화면에 꽉 차게(가운데 기준으로 잘라서) 맞춥니다."""
    scale = max(w / clip.w, h / clip.h)
    clip = clip.resized(scale)
    return clip.cropped(x_center=clip.w / 2, y_center=clip.h / 2, width=w, height=h)


class SceneBuilder:
    def __init__(self, project: Project, w: int, h: int, cfg: dict, mode: str = "cover"):
        self.project, self.w, self.h, self.cfg, self.mode = project, w, h, cfg, mode
        self.opened: list = []
        self.sources: dict[str, object] = {}

    def _video_source(self, path: Path):
        from moviepy import VideoFileClip
        key = str(path)
        if key not in self.sources:
            clip = VideoFileClip(key, audio=False)
            self.opened.append(clip)
            self.sources[key] = clip
        return self.sources[key]

    def _segment(self, m: dict, d: float, offset: float, seed: int):
        """소재 하나를 d초짜리 화면 조각으로. 쇼츠 'blur' 모드면 흐린 배경 위에 16:9로 놓습니다."""
        from moviepy import CompositeVideoClip, ImageClip

        path = resolve_path(self.project, m["path"])
        inner_w, inner_h = self.w, self.h
        if self.mode == "blur":
            inner_h = round(self.w * 9 / 16) // 2 * 2
        if m["kind"] == "video":
            src = self._video_source(path)
            start = offset % max(src.duration - d, 0.01) if src.duration > d else 0
            seg = fit_video(src.subclipped(start, min(start + d, src.duration)), inner_w, inner_h)
            seg = seg.with_duration(d)
            still = Image.fromarray(src.get_frame(min(start, src.duration - 0.05)))
        else:
            seg = ken_burns_clip(path, d, inner_w, inner_h, seed)
            still = Image.open(path)
        if self.mode != "blur":
            return seg
        bg = ImageClip(blurred_background(still, self.w, self.h)).with_duration(d)
        return CompositeVideoClip([bg, seg.with_position("center")], size=(self.w, self.h)).with_duration(d)

    def visual(self, scene: dict, length: float):
        from moviepy import ColorClip, concatenate_videoclips

        media = [m for m in scene.get("media", [])
                 if m.get("kind") in ("video", "image") and resolve_path(self.project, m["path"]).exists()]
        if not media:
            return ColorClip((self.w, self.h), color=(24, 28, 40), duration=length)
        img_secs = float(self.cfg["assets"]["image_seconds"])
        video_total = sum(min(m.get("duration") or 0, length) for m in media if m["kind"] == "video")
        n_img = sum(1 for m in media if m["kind"] == "image")
        img_each = max(img_secs, (length - video_total) / n_img) if n_img and video_total < length else img_secs

        segs, t, i = [], 0.0, 0
        passes: dict[int, int] = {}
        while length - t > 0.05 and i < 60:
            idx = i % len(media)
            m = media[idx]
            remaining = length - t
            if m["kind"] == "video":
                src_d = self._video_source(resolve_path(self.project, m["path"])).duration or 0
                d = min(max(src_d - 0.1, 0), remaining)
                if d < 0.3:
                    i += 1
                    continue
            else:
                d = min(img_each, remaining)
            leftover = remaining - d
            if 0 < leftover < 0.8:            # 끝에 깜빡이는 아주 짧은 조각이 남지 않게
                if m["kind"] == "image":
                    d = remaining
                elif d > 2.5:
                    d = remaining - 1.5
            n = passes.get(idx, 0)
            segs.append(self._segment(m, d, offset=n * 3.0, seed=hash((scene["id"], i)) & 0xFFFF))
            passes[idx] = n + 1
            t += d
            i += 1
        if not segs:
            return ColorClip((self.w, self.h), color=(24, 28, 40), duration=length)
        clip = segs[0] if len(segs) == 1 else concatenate_videoclips(segs, method="chain")
        return clip.with_duration(length)

    def close(self):
        for c in self.opened:
            try:
                c.close()
            except Exception:
                pass


# ---------------- 글자 겹치기 ----------------
def text_clip(text: str, style: SubtitleStyle, start: float, duration: float, y: int, frame_w: int):
    from moviepy import ImageClip
    img = render_text_image(text, style, max_width=int(frame_w * 0.94))
    return (ImageClip(np.asarray(img)).with_start(start).with_duration(max(duration, 0.05))
            .with_position(("center", y)))


def subtitle_clips(scene: dict, length: float, style: SubtitleStyle, w: int, h: int, bottom_pct: float,
                   max_chars: int, max_lines: int) -> list:
    clips = []
    for c in scene_cues(scene, max_chars, max_lines):
        if c["start"] >= length:
            continue
        img_h = render_text_image(c["text"], style).height
        y = int(h * (1 - bottom_pct / 100)) - img_h
        clips.append(text_clip(c["text"], style, c["start"], min(c["end"], length) - c["start"], y, w))
    return clips


def headline_style(style: SubtitleStyle) -> SubtitleStyle:
    from dataclasses import replace
    return replace(style, font_size=round(style.font_size * 1.3), color="#FFE14D",
                   stroke_width=max(2, round(style.stroke_width * 1.2)), box_color="#00000088")


# ---------------- 배경음악 ----------------
def duck_envelope(speech: list[tuple[float, float]], total: float, base: float, duck: float,
                  ramp: float = 0.35, fade: float = 1.5):
    merged: list[list[float]] = []
    for a, b in sorted(speech):
        if merged and a - merged[-1][1] < 2 * ramp + 0.3:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    xs, ys = [0.0], [base]
    for a, b in merged:
        a0, b1 = max(a - ramp, xs[-1] + 1e-3), b + ramp
        xs += [a0, max(a, a0 + 1e-3), max(b, a0 + 2e-3), max(b1, a0 + 3e-3)]
        ys += [base, duck, duck, base]
    xs.append(max(total, xs[-1] + 1e-3))
    ys.append(base)
    xp, fp = np.array(xs), np.array(ys)

    def env(t):
        t = np.asarray(t, dtype=float)
        v = np.interp(t, xp, fp)
        v = v * np.clip(t / fade, 0, 1) * np.clip((total - t) / fade, 0, 1)
        return v
    return env


def bgm_clip(path: Path, total: float, env):
    from moviepy import AudioFileClip, afx
    clip = AudioFileClip(str(path))
    if clip.duration < total:
        clip = clip.with_effects([afx.AudioLoop(duration=total)])
    clip = clip.subclipped(0, total)

    def apply(get_frame, t):
        frame = get_frame(t)
        v = env(t)
        return frame * (v[:, None] if np.ndim(v) else v)
    return clip.transform(apply, keep_duration=True)


# ---------------- 쇼츠 장면 선택 ----------------
def select_shorts_scenes(scenes: list[dict], max_seconds: float, padding: float) -> list[dict]:
    picked = [s for s in scenes if s.get("shorts")]
    if not picked:
        picked = [s for s in scenes if s.get("type") == "hook"] + \
                 [s for s in scenes if s.get("type") == "body"]
    out, total = [], 0.0
    for s in picked:
        length = float(s.get("duration") or 2) + padding
        if total + length <= max_seconds:
            out.append(s)
            total += length
    if not out and picked:  # 첫 장면 하나만으로도 길면 잘라서 사용
        s = dict(picked[0])
        s["duration"] = max_seconds - padding
        s["trimmed"] = True
        out = [s]
    return out


# ---------------- 메인 ----------------
def render_video(project: Project, *, shorts: bool = False, bgm: str | None = None, burn_subtitles: bool = True,
                 quality: str = "1080p", progress: Callable[[float, str], None] | None = None,
                 cfg: dict | None = None, size: tuple[int, int] | None = None) -> Path:
    from moviepy import AudioFileClip, CompositeAudioClip, CompositeVideoClip, concatenate_videoclips

    cfg = cfg or load_config()
    rcfg = cfg["render"]
    if not find_ffmpeg():
        raise UserFacingError("❌ ffmpeg를 찾지 못했어요. README의 'ffmpeg 설치' 부분을 따라 설치해 주세요.")
    data = project.load_scenes()
    if not data or not data.get("scenes"):
        raise UserFacingError("❌ 장면 정보가 없어요. ③ 내레이션과 ④ 소재 단계를 먼저 실행해 주세요.")
    scenes = data["scenes"]
    padding = float(rcfg["scene_padding"])
    if shorts:
        scenes = select_shorts_scenes(scenes, float(rcfg["shorts_max_seconds"]), padding)
    if not scenes:
        raise UserFacingError("❌ 쇼츠에 넣을 장면을 고르지 못했어요. 대본 표에서 shorts 칸을 체크해 주세요.")

    base_w, base_h = PORTRAIT if shorts else LANDSCAPE
    factor = QUALITY.get(quality, 1.0)
    w, h = size or (round(base_w * factor) // 2 * 2, round(base_h * factor) // 2 * 2)
    scale = w / base_w
    settings = project.get_settings()
    max_chars = int(settings.get("sub_max_chars") or cfg["subtitles"]["max_chars_per_line"])
    max_lines = int(settings.get("sub_max_lines") or cfg["subtitles"]["max_lines"])
    style_over = settings.get("sub_style") or {}
    style = SubtitleStyle.from_config(cfg, **style_over).scaled(scale * (1.15 if shorts else 1.0))
    bottom_pct = 28.0 if shorts else float(style_over.get("bottom_margin_pct", cfg["subtitles"]["bottom_margin_pct"]))
    head_style = headline_style(style)

    mode = rcfg["shorts_fit"] if shorts else "cover"
    builder = SceneBuilder(project, w, h, cfg, mode="blur" if mode == "blur" else "cover")
    timeline = scene_timeline(scenes, padding)
    total = sum(length for _, length in timeline)
    scene_clips, narrations, speech = [], [], []
    try:
        for n, (sc, (start, length)) in enumerate(zip(scenes, timeline)):
            if progress:
                progress(0.0, f"장면 준비 중… ({n + 1}/{len(scenes)})")
            layers = [builder.visual(sc, length)]
            if sc.get("on_screen_text") and not shorts:
                layers.append(text_clip(sc["on_screen_text"], head_style, 0,
                                        min(float(rcfg["on_screen_text_seconds"]), length), int(h * 0.08), w))
            if burn_subtitles:
                layers += subtitle_clips(sc, length, style, w, h, bottom_pct, max_chars, max_lines)
            scene_clips.append(CompositeVideoClip(layers, size=(w, h)).with_duration(length))
            if sc.get("audio"):
                a = AudioFileClip(str(project.path / sc["audio"]))
                builder.opened.append(a)
                if sc.get("trimmed"):
                    a = a.subclipped(0, min(a.duration, float(sc["duration"])))
                narrations.append(a.with_start(start))
                speech.append((start, start + min(a.duration, length)))

        video = concatenate_videoclips(scene_clips, method="chain")
        if shorts:
            title = data.get("thumbnail_text") or data.get("title") or ""
            if title:
                video = CompositeVideoClip([video, text_clip(title, head_style, 0, total, int(h * 0.1), w)],
                                           size=(w, h)).with_duration(total)

        audio_layers = list(narrations)
        bgm_path = _pick_bgm(bgm)
        if bgm_path:
            env = duck_envelope(speech, total, float(rcfg["bgm_volume"]), float(rcfg["bgm_duck_volume"]))
            b = bgm_clip(bgm_path, total, env)
            builder.opened.append(b)
            audio_layers.append(b)
        if audio_layers:
            video = video.with_audio(CompositeAudioClip(audio_layers).with_duration(total))

        out = project.shorts_video if shorts else project.final_video
        out.parent.mkdir(parents=True, exist_ok=True)
        video.write_videofile(
            str(out), fps=int(rcfg["fps"]), codec="libx264", audio_codec="aac", audio_bitrate="192k",
            preset=rcfg["preset"], threads=os.cpu_count() or 4, pixel_format="yuv420p",
            temp_audiofile=str(out.with_name(out.stem + "_temp_audio.m4a")),
            logger=CallbackLogger(progress) if progress else None,
        )
    except OSError as e:
        raise UserFacingError(f"❌ 영상 파일을 읽거나 쓰는 중 문제가 생겼어요: {e}\n"
                              "결과 영상이 다른 프로그램(동영상 플레이어 등)에서 열려 있다면 닫고 다시 시도해 주세요.") from e
    finally:
        builder.close()
    if progress:
        progress(1.0, "완료!")
    return out


def _pick_bgm(bgm: str | None) -> Path | None:
    if not bgm or bgm == "없음":
        return None
    files = list_bgm()
    if bgm == "랜덤":
        return random.choice(files) if files else None
    p = Path(bgm)
    if not p.is_absolute():
        p = BGM_DIR / bgm
    return p if p.exists() else None


def render_all(project: Project, *, make_shorts: bool = True, bgm: str | None = None, burn_subtitles: bool = True,
               quality: str = "1080p", progress: Callable[[float, str], None] | None = None) -> list[Path]:
    project.invalidate_from("render")
    outputs = []

    def sub_progress(lo, hi):
        return (lambda p, m: progress(lo + (hi - lo) * p, m)) if progress else None

    main_end = 0.8 if make_shorts else 1.0
    outputs.append(render_video(project, bgm=bgm, burn_subtitles=burn_subtitles, quality=quality,
                                progress=sub_progress(0, main_end)))
    if make_shorts:
        outputs.append(render_video(project, shorts=True, bgm=bgm, burn_subtitles=True, quality=quality,
                                    progress=sub_progress(main_end, 1.0)))
    project.mark_done("render", outputs=[str(p.relative_to(project.path)) for p in outputs])
    return outputs
