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
import math
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import subtitle_style
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
    for c in sorted(fonts_dir.glob("*.otf")) + sorted(fonts_dir.glob("*.ttf")):   # 직접 넣은 폰트가 최우선
        return c
    try:  # Pretendard 무료 폰트 자동 다운로드 (SIL OFL 1.1) — 자막이 가장 깔끔하게 나와요
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
    for c in (Path("C:/Windows/Fonts/malgunbd.ttf"), Path("C:/Windows/Fonts/malgun.ttf"),
              Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"), Path("/Library/Fonts/AppleGothic.ttf"),
              Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
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
        g = "m" if subtitle_style.is_male(c) else "f"
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


WINDOWS_TTS_PS1 = r"""
param([string]$TextFile, [string]$WavFile, [string]$Pitch, [string]$Rate)
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$v = $s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo } | Where-Object { $_.Culture.Name -eq 'ko-KR' } | Select-Object -First 1
if (-not $v) { exit 3 }
$s.SelectVoice($v.Name)
$s.Rate = [int]$Rate
$t = [IO.File]::ReadAllText($TextFile, [Text.Encoding]::UTF8)
$e = [Security.SecurityElement]::Escape($t)
$ssml = "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='ko-KR'><prosody pitch='$Pitch'>$e</prosody></speak>"
$s.SetOutputToWaveFile($WavFile)
$s.SpeakSsml($ssml)
$s.Dispose()
"""


def is_male_voice(voice: dict) -> bool:
    return any(k in voice.get("voice", "") for k in ("InJoon", "Hyunsu", "Male"))


def windows_tts_synth(text: str, voice: dict, out: Path) -> None:
    """윈도우에 기본으로 들어 있는 한국어 목소리(인터넷 불필요). 남자 인물은 목소리를 낮춥니다."""
    import sys
    if sys.platform != "win32":
        raise EditError("윈도우 기본 목소리는 윈도우에서만 쓸 수 있어요.")
    tmp = out.with_suffix("")
    ps1, txt, wav = tmp.with_name(tmp.name + ".ps1"), tmp.with_name(tmp.name + ".txt"), tmp.with_name(tmp.name + ".wav")
    ps1.write_text(WINDOWS_TTS_PS1, encoding="utf-8-sig")
    txt.write_text(text, encoding="utf-8")
    pitch = "low" if is_male_voice(voice) else "medium"
    rate = "1" if voice.get("rate", "+0%").startswith("+") and voice.get("rate") != "+0%" else "0"
    try:
        p = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1),
                            str(txt), str(wav), pitch, rate], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        if p.returncode == 3:
            raise EditError("윈도우에 한국어 음성이 없어요. 설정 → 시간 및 언어 → 언어 및 지역 → 한국어 → "
                            "언어 옵션 → '음성' 을 설치해 주세요.")
        if p.returncode != 0 or not wav.exists():
            raise RuntimeError((p.stderr or p.stdout or "PowerShell 오류").strip().splitlines()[-1][:200])
        _run(["-i", str(wav), "-ar", "44100", "-ac", "2", "-b:a", "160k", str(out)])
    finally:
        for f in (ps1, txt, wav):
            f.unlink(missing_ok=True)


class VoiceEngine:
    """mode: auto(인터넷 무료 목소리 → 막히면 윈도우 목소리) / edge / windows"""
    ENGINES = {"edge": edge_tts_synth, "windows": windows_tts_synth}

    def __init__(self, mode: str = "auto", log=print, synth=None):
        mode = (mode or "auto").lower()
        if synth is not None:                       # 테스트 등에서 직접 넣은 엔진
            self.order = [("custom", synth)]
        elif mode in self.ENGINES:
            self.order = [(mode, self.ENGINES[mode])]
        else:
            self.order = [("edge", self.ENGINES["edge"]), ("windows", self.ENGINES["windows"])]
        self.log = log

    @property
    def name(self) -> str:
        return self.order[0][0]

    RETRIES = 3          # 인터넷 목소리는 연결이 가끔 끊기므로 몇 번 다시 시도
    WAIT = 2.0           # 다시 시도 전 기다리는 시간(초), 시도할수록 늘어남

    def __call__(self, text: str, voice: dict, out: Path) -> str:
        """음성을 만들고, 실제로 쓴 엔진 이름을 돌려줍니다."""
        import time
        while True:
            name, fn = self.order[0]
            tries = self.RETRIES if name == "edge" else 1
            for attempt in range(1, tries + 1):
                try:
                    fn(text, voice, out)
                    return name
                except EditError:
                    raise
                except Exception as e:
                    out.unlink(missing_ok=True)
                    err = e
                    if attempt < tries:
                        time.sleep(self.WAIT * attempt)
            if len(self.order) == 1:
                raise err
            detail = str(err).strip().splitlines()[0][:160] if str(err).strip() else ""
            self.log(f"  ⚠ 인터넷 무료 목소리가 {tries}번 연속 끊겼어요 ({type(err).__name__}: {detail})\n"
                     "     → 남은 대사는 윈도우 기본 한국어 목소리로 만들어요. 나중에 edit 를 다시 실행하면\n"
                     "       그 대사들도 인터넷 목소리로 다시 시도해요(이미 된 대사는 그대로 둠).")
            self.order.pop(0)


# ── 화면 재료 ───────────────────────────────────────────
def _wrap(text: str, width: int = 14) -> list[str]:
    lines = []
    for para in text.split("\n"):
        lines += textwrap.wrap(para, width=width, break_long_words=True) or [""]
    return lines


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
def plan_cut(cut: dict, voice_files: list[tuple[Path, float]], single_voice: bool,
             lead: float = LEAD) -> tuple[float, list[dict]]:
    """컷 길이와 자막·음성 타이밍을 계산합니다. lead = 대사 시작 전 여유(앞 전환이 끝난 뒤).
    반환: (길이, [{text, start, end, audio}])"""
    lines = [d["line"] for d in cut["dialogue"]]
    speakers = [d["speaker"] for d in cut["dialogue"]]
    events = []
    if single_voice and voice_files:              # 직접 넣은 음성 파일 하나 = 컷 전체 대사
        path, dur = voice_files[0]
        length = max(cut["seconds"], lead + dur + TAIL)
        span = dur / max(1, len(lines))
        for i, t in enumerate(lines):
            events.append({"text": t, "start": lead + i * span, "end": lead + (i + 1) * span,
                           "audio": path if i == 0 else None, "speaker": speakers[i]})
        return length, events
    if voice_files:                               # 대사 줄마다 TTS
        t = lead
        for text, (path, dur) in zip(lines, voice_files):
            events.append({"text": text, "start": t, "end": t + dur, "audio": path,
                           "speaker": speakers[len(events)]})
            t += dur + GAP
        return max(cut["seconds"], t - GAP + TAIL), events
    length = float(cut["seconds"])                # 음성 없음: 자막만 고르게 배치
    if lines:
        span = (length - lead - LEAD) / len(lines)
        events = [{"text": t, "start": lead + i * span, "end": lead + (i + 1) * span, "audio": None,
                   "speaker": speakers[i]}
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
        args += ["-loop", "1", "-framerate", str(FPS), "-t", f"{length:.3f}", "-i", str(png)]
        f = min(0.15, (ev["end"] - ev["start"]) / 3)          # 자막이 부드럽게 나타나고 사라짐
        chain.append(f"[{n_in}:v]format=rgba,fade=t=in:st={ev['start']:.3f}:d={f:.3f}:alpha=1,"
                     f"fade=t=out:st={ev['end'] - f:.3f}:d={f:.3f}:alpha=1[s{n_in}]")
        chain.append(f"[{last}][s{n_in}]overlay=0:0:format=auto[v{n_in}]")
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


# ── 장면 전환 ───────────────────────────────────────────
# 이름: (ffmpeg xfade 효과, 길이초).  cut = 효과 없이 바로 넘어감
TRANSITIONS = {
    "cut": (None, 0.0),
    "dissolve": ("fade", 0.5),          # 부드럽게 겹치며 넘어감 (장소가 바뀔 때)
    "fade_black": ("fadeblack", 0.8),   # 검은 화면을 거쳐 넘어감 (시간이 흐를 때)
    "flash_white": ("fadewhite", 0.4),  # 하얗게 번쩍 (회상·충격·설렘 순간)
    "slide": ("slideleft", 0.4),        # 옆으로 밀어내기
}
TIME_JUMP = re.compile(r"next|later|morning after|days?|weeks?|다음|며칠|후|뒤", re.I)


def plan_transitions(cuts: list[dict], mode: str = "auto") -> list[str]:
    """컷 사이(n-1개)의 전환 효과를 정합니다.
    auto: 대본에 적힌 전환을 따르고, 없으면 시간이 흐르면 fade_black, 장소/시간대가 바뀌면 dissolve, 아니면 cut.
    none: 모두 cut.  그 밖의 이름(dissolve 등): 모든 컷 사이에 그 효과."""
    mode = (mode or "auto").strip().lower()
    if mode in ("none", "off", "cut"):
        return ["cut"] * max(0, len(cuts) - 1)
    if mode in TRANSITIONS:
        return [mode] * max(0, len(cuts) - 1)
    out = []
    for a, b in zip(cuts, cuts[1:]):
        t = a.get("transition", "")
        if t not in TRANSITIONS:
            if a["time_of_day"] != b["time_of_day"] and TIME_JUMP.search(b["time_of_day"]):
                t = "fade_black"
            elif a["location"] != b["location"] or a["time_of_day"] != b["time_of_day"]:
                t = "dissolve"
            else:
                t = "cut"
        out.append(t)
    return out


def join_segments(segs: list[Path], lengths: list[float], trans: list[str], out: Path,
                  end_fade: float = 0.0) -> None:
    """컷 영상을 이어 붙입니다. 각 컷은 다음 전환 길이만큼 미리 늘려 두었기 때문에,
    전환이 있어도 전체 길이와 자막 시간은 바뀌지 않습니다."""
    total = sum(lengths)
    if all(t == "cut" for t in trans) and end_fade <= 0:      # 효과 없음: 다시 인코딩하지 않고 빠르게
        listfile = out.with_suffix(".txt")
        listfile.write_text("".join(f"file '{s.resolve().as_posix()}'\n" for s in segs), encoding="utf-8")
        _run(["-f", "concat", "-safe", "0", "-i", str(listfile), "-c", "copy", str(out)])
        return
    args, chain = [], []
    for i, s in enumerate(segs):
        args += ["-i", str(s)]
        chain.append(f"[{i}:v]fps={FPS},settb=AVTB,setpts=PTS-STARTPTS[sv{i}]")  # 시간 기준을 모두 같게
        chain.append(f"[{i}:a]aresample=44100,asetpts=PTS-STARTPTS[sa{i}]")
    v, a, acc = "[sv0]", "[sa0]", lengths[0]
    for i in range(1, len(segs)):
        name, d = TRANSITIONS[trans[i - 1]]
        if name is None:
            chain.append(f"{v}{a}[sv{i}][sa{i}]concat=n=2:v=1:a=1[v{i}][a{i}]")
        else:
            chain.append(f"{v}[sv{i}]xfade=transition={name}:duration={d}:offset={acc:.4f},settb=AVTB[v{i}]")
            chain.append(f"{a}[sa{i}]acrossfade=d={d}[a{i}]")
        v, a = f"[v{i}]", f"[a{i}]"
        acc += lengths[i]
    if end_fade > 0:
        st = max(0.0, total - end_fade)
        chain.append(f"{v}fade=t=out:st={st:.3f}:d={end_fade}[vend]")
        chain.append(f"{a}afade=t=out:st={st:.3f}:d={end_fade}[aend]")
        v, a = "[vend]", "[aend]"
    args += ["-filter_complex", ";".join(chain), "-map", v, "-map", a, "-t", f"{total:.3f}",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS),
             "-c:a", "aac", "-b:a", "160k", "-ar", "44100", str(out)]
    _run(args)


def duck_volume_expr(spans: list[tuple[float, float]], duck: float, ramp: float = 0.3) -> str:
    """대사 구간마다 배경음악을 duck 배로 줄이는 볼륨 필터. 갑자기 툭 줄지 않게 ramp 초 동안 서서히 줄고 돌아옵니다.
    줄일 구간이 없거나 duck >= 1 이면 빈 문자열."""
    if not spans or duck >= 1:
        return ""
    merged: list[list[float]] = []
    for a, b in sorted(spans):                       # 가까운 대사 구간은 하나로 합침 (사이에 음악이 출렁이지 않게)
        if merged and a - merged[-1][1] < max(2 * ramp, 1.5):   # 주고받는 대화 중엔 계속 낮게
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    terms = [f"clip((t-{a - ramp:.3f})/{ramp},0,1)*clip(({b + ramp:.3f}-t)/{ramp},0,1)" for a, b in merged]
    m = terms[0]
    for t in terms[1:]:
        m = f"max({m},{t})"
    return f"volume=eval=frame:volume='1-{1 - duck:.3f}*{m}',"


# ── 회차 전체 ───────────────────────────────────────────
def _voice_summary(voiced: int, need: int, engines: set) -> str:
    """대사가 있는 컷 중 몇 컷에 목소리가 들어갔는지 정확히 알려줍니다."""
    if need == 0:
        return " / 대사 없음"
    how = " (윈도우 기본 목소리 섞임)" if "windows" in engines and len(engines) > 1 else \
          " (윈도우 기본 목소리)" if engines == {"windows"} else ""
    if voiced == 0:
        return " / 음성 없음(자막만)"
    return f" / 음성 {voiced}/{need}컷{how}"


def _voice_key(line: str, voice: dict, engine: str) -> str:
    return hashlib.md5(f"{line}|{voice}|{engine}".encode()).hexdigest()[:10]


def _srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def edit_episode(out_dir: Path, series: dict, ep_no: int, cfg: dict, tts: bool = True,
                 synth=None, log=print) -> Path:
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
    style = str(cfg.get("edit", {}).get("subtitle_style", "romance")).lower()
    style = style if style in subtitle_style.STYLES else "romance"
    size = int(cfg.get("edit", {}).get("subtitle_size", 58))
    show_speaker = bool(cfg.get("edit", {}).get("show_speaker", True))
    colors = subtitle_style.char_colors(series["bible"], cfg.get("edit", {}).get("subtitle_colors"))
    names = {c["id"]: c["name"] for c in series["bible"]["characters"]}
    ecfg = cfg.get("edit", {})
    engine = VoiceEngine(str(ecfg.get("tts", "auto")), log, synth)

    trans = plan_transitions(ep["cuts"], str(ecfg.get("transition", "auto")))
    pads = [TRANSITIONS[t][1] for t in trans] + [0.0]
    segs, lengths, srt, t0 = [], [], [], 0.0
    counts = {"video": 0, "image": 0, "placeholder": 0, "clip_audio": 0}
    voiced, used_engines = 0, set()
    for idx, cut in enumerate(ep["cuts"]):
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
                    mp3 = work / f"{stem}_{i + 1}_{_voice_key(d['line'], v, engine.name)}.mp3"
                    if not mp3.exists() or mp3.stat().st_size == 0:   # 빈 파일 = 지난번 실패 → 다시 생성
                        try:
                            used = engine(d["line"], v, mp3)
                            used_engines.add(used)
                        except BaseException:
                            mp3.unlink(missing_ok=True)
                            raise
                        real = work / f"{stem}_{i + 1}_{_voice_key(d['line'], v, used)}.mp3"
                        if real != mp3:                                # 도중에 엔진이 바뀐 경우 이름 정리
                            mp3.replace(real)
                            mp3 = real
                    voice_files.append((mp3, media_duration(mp3)))
            except EditError:
                raise
            except Exception as e:  # 인터넷이 없거나 TTS 서버 문제
                detail = str(e).strip().splitlines()[0][:200] if str(e).strip() else ""
                log(f"  ⚠ 음성(TTS) 생성 실패 → 이번 편집은 자막만 넣어요. ({type(e).__name__}: {detail})\n"
                    "     · 인터넷 연결, 백신·보안 프로그램이 speech.platform.bing.com 접속을 막는지 확인하세요.\n"
                    "     · 대신 뉴테이크 '오디오 생성' 등으로 만든 음성을 clips/EP01/cut01_voice.mp3 처럼 넣어도 돼요.")
                tts, voice_files = False, []

        lead = max(LEAD, pads[idx - 1] + 0.1) if idx > 0 and pads[idx - 1] > 0 else LEAD  # 전환이 끝난 뒤 대사 시작
        voiced += bool(voice_files)
        length, events = plan_cut(cut, voice_files, single, lead)
        length = math.ceil(length * FPS - 1e-6) / FPS             # 프레임 단위로 맞춤
        subs = []
        for i, ev in enumerate(events):
            png = work / f"{stem}_sub{i + 1}.png"
            who = names.get(ev.get("speaker", ""), "")
            subtitle_style.render(ev["text"], font, png, style, size,
                                  who if show_speaker else "", colors.get(ev.get("speaker", ""), "#FF8FB1"))
            subs.append(png)
            srt.append((t0 + ev["start"], t0 + ev["end"], ev["text"]))
        seg = work / f"{stem}.mp4"
        nxt = f" → {trans[idx]}" if idx < len(trans) and trans[idx] != "cut" else ""
        log(f"  · 컷 {cut['no']:>2} ({kind}, {length:.1f}초){nxt}")
        cvol = float(ecfg.get("clip_volume", 0.7)) if kind == "video" and has_audio(src) else 0.0
        counts["clip_audio"] += cvol > 0
        render_cut(src, "video" if kind == "video" else "image", length + pads[idx], events, subs, seg,
                   cvol, float(ecfg.get("clip_duck", 0.35)))
        segs.append(seg)
        lengths.append(length)
        t0 += length

    # 이어 붙이기 (장면 전환 포함)
    joined = work / "joined.mp4"
    join_segments(segs, lengths, trans, joined, float(ecfg.get("end_fade", 1.0)))

    final = out_dir / f"05_완성_{tag}.mp4"
    bgm = _find(out_dir / "clips", "bgm", AUDIO_EXT)
    if bgm:
        vol = float(ecfg.get("bgm_volume", 0.12))
        fade = max(0.0, t0 - 2)
        duck = duck_volume_expr([(a, b) for a, b, _ in srt], float(ecfg.get("bgm_duck", 0.4)))
        _run(["-i", str(joined), "-stream_loop", "-1", "-i", str(bgm), "-filter_complex",
              f"[1:a]volume={vol},{duck}afade=t=in:d=1,afade=t=out:st={fade:.2f}:d=2[b];"
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
        + f" / 전환 효과 {sum(t != 'cut' for t in trans)}곳"
        + (" / 배경음악 O" if bgm else " / 배경음악 없음") + _voice_summary(voiced, sum(bool(c["dialogue"]) for c in ep["cuts"]), used_engines))
    return final
