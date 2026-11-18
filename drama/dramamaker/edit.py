"""자동 편집: 뉴테이크에서 받은 컷 영상 + 대사 음성(TTS) + 자막 + 배경음악 → 완성 영상(9:16 mp4).

폴더 규칙 (결과 폴더 안)
  clips/EP01/cut01.mp4   ← 뉴테이크에서 받은 컷 영상 (mp4/mov/webm)
  clips/EP01/cut01.png   ← 영상이 아직 없으면 시작 이미지로 대신 (천천히 확대 효과)
  clips/EP01/cut01_voice.mp3 ← 직접 녹음/다른 TTS 음성을 쓰고 싶을 때 (선택)
  clips/bgm.mp3          ← 배경음악 (선택)
아무 파일도 없는 컷은 '영상 대기 중' 화면으로 채워, 미리보기(콘티 영상)를 먼저 볼 수 있습니다.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .settings import BASE_DIR

W, H, FPS = 1080, 1920, 30
VIDEO_EXT = (".mp4", ".mov", ".webm", ".mkv", ".m4v")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")
AUDIO_EXT = (".mp3", ".wav", ".m4a", ".aac", ".ogg")
LEAD, GAP, TAIL = 0.3, 0.25, 0.5          # 대사 시작 전 여유, 대사 사이 간격, 끝 여유(초)

FEMALE, MALE = "ko-KR-SunHiNeural", "ko-KR-InJoonNeural"
PITCHES = ["+0Hz", "+12Hz", "-10Hz", "+22Hz"]   # 같은 성별 인물이 여럿이면 목소리 높이를 다르게


class EditError(RuntimeError):
    pass


# ── 도구 ────────────────────────────────────────────────
def ffmpeg_exe() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        raise EditError("ffmpeg 를 찾지 못했어요. 'pip install -r requirements.txt' 를 다시 실행해 주세요.") from e


def _run(args: list[str]) -> None:
    p = subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise EditError("영상 처리(ffmpeg) 중 오류가 났어요:\n" + p.stderr.strip()[-1500:])


def media_duration(path: Path) -> float:
    p = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", p.stderr)
    if not m:
        raise EditError(f"파일 길이를 읽지 못했어요: {path.name}")
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def has_audio(path: Path) -> bool:
    p = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return bool(re.search(r"Stream #.*Audio:", p.stderr))


def find_font(fonts_dir: Path) -> Path:
    cands = sorted(fonts_dir.glob("*.otf")) + sorted(fonts_dir.glob("*.ttf")) + [
        Path("C:/Windows/Fonts/malgunbd.ttf"), Path("C:/Windows/Fonts/malgun.ttf"),
        Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"),
        Path("/Library/Fonts/AppleGothic.ttf")]
    for c in cands:
        if c.exists():
            return c
    try:  # Pretendard 무료 폰트 자동 다운로드 (SIL OFL 1.1)
        import requests
        url = ("https://raw.githubusercontent.com/orioncactus/pretendard/main/packages/pretendard/"
               "dist/public/static/Pretendard-Bold.otf")
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        fonts_dir.mkdir(parents=True, exist_ok=True)
        path = fonts_dir / "Pretendard-Bold.otf"
        path.write_bytes(r.content)
        return path
    except Exception:
        pass
    for c in (Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
              Path("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf")):
        if c.exists():
            return c
    raise EditError(f"한글 폰트를 찾지 못했어요. .ttf/.otf 한글 폰트 파일을 {fonts_dir} 에 넣어 주세요.")


# ── 음성(TTS) ───────────────────────────────────────────
def assign_voices(bible: dict, overrides: dict | None = None) -> dict:
    """인물별 목소리: config 의 voices 가 우선, 없으면 voice 설명의 '남/여'로 고르고 높이를 달리합니다."""
    overrides = overrides or {}
    out, count = {}, {"m": 0, "f": 0}
    for c in bible["characters"]:
        g = "m" if re.search(r"남(성|자)|male|man", c.get("voice", "") + c.get("look_en", ""), re.I) \
            and not re.search(r"여(성|자)|female|woman", c.get("voice", "")) else "f"
        pitch = PITCHES[count[g] % len(PITCHES)]
        count[g] += 1
        o = overrides.get(c["id"]) or {}
        if isinstance(o, str):
            o = {"voice": o}
        out[c["id"]] = {"voice": o.get("voice", MALE if g == "m" else FEMALE),
                        "pitch": o.get("pitch", pitch), "rate": o.get("rate", "+0%")}
    return out


def edge_tts_synth(text: str, voice: dict, out: Path) -> None:
    import edge_tts

    async def _go():
        await edge_tts.Communicate(text, voice["voice"], rate=voice["rate"], pitch=voice["pitch"]).save(str(out))
    asyncio.run(_go())


# ── 화면 재료 ───────────────────────────────────────────
def _wrap(text: str, width: int = 14) -> list[str]:
    lines = []
    for para in text.split("\n"):
        lines += textwrap.wrap(para, width=width, break_long_words=True) or [""]
    return lines


def subtitle_png(text: str, font_path: Path, out: Path, size: int = 64, y: int = 1430) -> None:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(font_path), size)
    for i, line in enumerate(_wrap(text)):
        d.text((W // 2, y + i * int(size * 1.3)), line, font=font, fill="white", anchor="ma",
               stroke_width=max(4, size // 12), stroke_fill="black")
    img.save(out)


def placeholder_png(cut: dict, ep_title: str, font_path: Path, out: Path) -> None:
    img = Image.new("RGB", (W, H), (24, 22, 30))
    d = ImageDraw.Draw(img)
    big, mid = ImageFont.truetype(str(font_path), 96), ImageFont.truetype(str(font_path), 50)
    d.text((W // 2, 300), f"컷 {cut['no']}", font=big, fill=(255, 200, 210), anchor="ma")
    d.text((W // 2, 430), ep_title, font=mid, fill=(170, 170, 185), anchor="ma")
    y = 650
    for line in _wrap(cut["action_ko"], 18):
        d.text((W // 2, y), line, font=mid, fill="white", anchor="ma")
        y += 72
    d.text((W // 2, y + 60), f"{cut['shot']} · {cut['location']}", font=mid, fill=(150, 150, 165), anchor="ma")
    d.text((W // 2, 1780), "영상 대기 중 (clips 폴더에 넣으면 자동 교체)",
           font=ImageFont.truetype(str(font_path), 40), fill=(120, 120, 135), anchor="ma")
    img.save(out)


def _find(folder: Path, stem: str, exts: tuple) -> Path | None:
    for ext in exts:
        for name in (stem + ext, stem + ext.upper()):
            if (folder / name).exists():
                return folder / name
    return None


# ── 컷 하나 만들기 ──────────────────────────────────────
def plan_cut(cut: dict, voice_files: list[tuple[Path, float]], single_voice: bool) -> tuple[float, list[dict]]:
    """컷 길이와 자막·음성 타이밍을 계산합니다. 반환: (길이, [{text, start, end, audio}])"""
    lines = [d["line"] for d in cut["dialogue"]]
    events = []
    if single_voice and voice_files:              # 직접 넣은 음성 파일 하나 = 컷 전체 대사
        path, dur = voice_files[0]
        length = max(cut["seconds"], LEAD + dur + TAIL)
        span = dur / max(1, len(lines))
        for i, t in enumerate(lines):
            events.append({"text": t, "start": LEAD + i * span, "end": LEAD + (i + 1) * span,
                           "audio": path if i == 0 else None})
        return length, events
    if voice_files:                               # 대사 줄마다 TTS
        t = LEAD
        for text, (path, dur) in zip(lines, voice_files):
            events.append({"text": text, "start": t, "end": t + dur, "audio": path})
            t += dur + GAP
        return max(cut["seconds"], t - GAP + TAIL), events
    length = float(cut["seconds"])                # 음성 없음: 자막만 고르게 배치
    if lines:
        span = (length - 2 * LEAD) / len(lines)
        events = [{"text": t, "start": LEAD + i * span, "end": LEAD + (i + 1) * span, "audio": None}
                  for i, t in enumerate(lines)]
    return length, events


def render_cut(src: Path, kind: str, length: float, events: list[dict], subs: list[Path], out: Path,
               clip_volume: float = 0.0, clip_duck: float = 1.0) -> None:
    """clip_volume > 0 이면 원본 영상의 소리를 그 크기로 넣고, 대사가 나오는 동안은 clip_duck 배로 더 줄입니다."""
    args: list[str] = []
    if kind == "video":
        args += ["-i", str(src)]
        vf = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={FPS},"
              f"tpad=stop_mode=clone:stop_duration={length:.3f},trim=duration={length:.3f},setpts=PTS-STARTPTS[bg]")
    else:  # 이미지: 천천히 확대(켄 번스 효과)
        frames = int(round(length * FPS))
        args += ["-loop", "1", "-framerate", str(FPS), "-t", f"{length:.3f}", "-i", str(src)]
        vf = (f"[0:v]scale={int(W * 1.2)}:{int(H * 1.2)}:force_original_aspect_ratio=increase,"
              f"crop={int(W * 1.2)}:{int(H * 1.2)},setsar=1,"
              f"zoompan=z='1+0.12*on/{max(1, frames)}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
              f":d=1:s={W}x{H}:fps={FPS},trim=duration={length:.3f},setpts=PTS-STARTPTS[bg]")
    n_in = 1
    chain, last = [vf], "bg"
    for ev, png in zip(events, subs):
        args += ["-loop", "1", "-t", f"{length:.3f}", "-i", str(png)]
        chain.append(f"[{last}][{n_in}:v]overlay=0:0:enable='between(t,{ev['start']:.3f},{ev['end']:.3f})'[v{n_in}]")
        last = f"v{n_in}"
        n_in += 1
    args += ["-f", "lavfi", "-t", f"{length:.3f}", "-i", "anullsrc=r=44100:cl=stereo"]
    sil = n_in
    n_in += 1
    mix = [f"[{sil}:a]"]
    if kind == "video" and clip_volume > 0:
        talk = events if any(e["audio"] for e in events) else []  # 음성이 있는 컷만 줄이기
        duck = ""
        if talk and clip_duck < 1:
            spans = "+".join(f"between(t,{ev['start'] - 0.15:.3f},{ev['end'] + 0.15:.3f})" for ev in talk)
            duck = f",volume={clip_duck}:enable='{spans}'"
        chain.append(f"[0:a]aresample=44100,aformat=channel_layouts=stereo,volume={clip_volume}{duck},"
                     f"apad,atrim=0:{length:.3f},asetpts=PTS-STARTPTS[clipa]")
        mix.append("[clipa]")
    for ev in events:
        if ev["audio"]:
            ms = int(ev["start"] * 1000)
            args += ["-i", str(ev["audio"])]
            chain.append(f"[{n_in}:a]aresample=44100,aformat=channel_layouts=stereo,adelay={ms}|{ms}[a{n_in}]")
            mix.append(f"[a{n_in}]")
            n_in += 1
    chain.append("".join(mix) + f"amix=inputs={len(mix)}:duration=first:normalize=0[aout]")
    args += ["-filter_complex", ";".join(chain), "-map", f"[{last}]", "-map", "[aout]",
             "-t", f"{length:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-b:a", "160k", "-ar", "44100", str(out)]
    _run(args)


# ── 회차 전체 ───────────────────────────────────────────
def _srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def edit_episode(out_dir: Path, series: dict, ep_no: int, cfg: dict, tts: bool = True,
                 synth=edge_tts_synth, log=print) -> Path:
    ep = next((e for e in series["episodes"] if e["no"] == ep_no), None)
    if not ep:
        raise EditError(f"EP{ep_no:02d} 가 series.json 에 없어요.")
    tag = f"EP{ep_no:02d}"
    clip_dir = out_dir / "clips" / tag
    clip_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "_편집작업" / tag
    work.mkdir(parents=True, exist_ok=True)
    font = find_font(BASE_DIR / "fonts")
    voices = assign_voices(series["bible"], cfg.get("voices"))
    ecfg = cfg.get("edit", {})

    segs, srt, t0, counts = [], [], 0.0, {"video": 0, "image": 0, "placeholder": 0, "clip_audio": 0}
    for cut in ep["cuts"]:
        stem = f"cut{cut['no']:02d}"
        src, kind = _find(clip_dir, stem, VIDEO_EXT), "video"
        if not src:
            src, kind = _find(clip_dir, stem, IMAGE_EXT), "image"
        if not src:
            src, kind = work / f"{stem}_대기.png", "placeholder"
            placeholder_png(cut, f"{tag}. {ep['title']}", font, src)
        counts[kind] += 1

        voice_files, single = [], False
        own = _find(clip_dir, f"{stem}_voice", AUDIO_EXT)
        if own:
            voice_files, single = [(own, media_duration(own))], True
        elif tts and cut["dialogue"]:
            try:
                for i, d in enumerate(cut["dialogue"]):
                    v = voices.get(d["speaker"], {"voice": FEMALE, "pitch": "+0Hz", "rate": "+0%"})
                    key = hashlib.md5(f"{d['line']}|{v}".encode()).hexdigest()[:10]
                    mp3 = work / f"{stem}_{i + 1}_{key}.mp3"
                    if not mp3.exists():
                        synth(d["line"], v, mp3)
                    voice_files.append((mp3, media_duration(mp3)))
            except EditError:
                raise
            except Exception as e:  # 인터넷이 없거나 TTS 서버 문제
                log(f"  ⚠ 음성(TTS) 생성 실패 → 이번 편집은 자막만 넣어요. 인터넷 연결을 확인하세요. ({type(e).__name__})")
                tts, voice_files = False, []

        length, events = plan_cut(cut, voice_files, single)
        subs = []
        for i, ev in enumerate(events):
            png = work / f"{stem}_sub{i + 1}.png"
            subtitle_png(ev["text"], font, png, int(ecfg.get("subtitle_size", 64)))
            subs.append(png)
            srt.append((t0 + ev["start"], t0 + ev["end"], ev["text"]))
        seg = work / f"{stem}.mp4"
        log(f"  · 컷 {cut['no']:>2} ({kind}, {length:.1f}초)")
        cvol = float(ecfg.get("clip_volume", 0.7)) if kind == "video" and has_audio(src) else 0.0
        counts["clip_audio"] += cvol > 0
        render_cut(src, "video" if kind == "video" else "image", length, events, subs, seg,
                   cvol, float(ecfg.get("clip_duck", 0.35)))
        segs.append(seg)
        t0 += length

    # 이어 붙이기
    listfile = work / "concat.txt"
    listfile.write_text("".join(f"file '{s.resolve().as_posix()}'\n" for s in segs), encoding="utf-8")
    joined = work / "joined.mp4"
    _run(["-f", "concat", "-safe", "0", "-i", str(listfile), "-c", "copy", str(joined)])

    final = out_dir / f"05_완성_{tag}.mp4"
    bgm = _find(out_dir / "clips", "bgm", AUDIO_EXT)
    if bgm:
        vol = float(ecfg.get("bgm_volume", 0.12))
        fade = max(0.0, t0 - 2)
        _run(["-i", str(joined), "-stream_loop", "-1", "-i", str(bgm), "-filter_complex",
              f"[1:a]volume={vol},afade=t=in:d=1,afade=t=out:st={fade:.2f}:d=2[b];"
              f"[0:a][b]amix=inputs=2:duration=first:normalize=0[a]",
              "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
              "-t", f"{t0:.3f}", str(final)])
    else:
        shutil.copyfile(joined, final)

    (out_dir / f"05_자막_{tag}.srt").write_text(
        "\n".join(f"{i}\n{_srt_time(a)} --> {_srt_time(b)}\n{txt}\n" for i, (a, b, txt) in enumerate(srt, 1)),
        encoding="utf-8")
    log(f"  · 영상 {counts['video']}컷 / 이미지 {counts['image']}컷 / 대기 화면 {counts['placeholder']}컷"
        + f" / 원본 소리 {counts['clip_audio']}컷"
        + (" / 배경음악 O" if bgm else " / 배경음악 없음") + (" / 음성 O" if tts else " / 음성 없음(자막만)"))
    return final
