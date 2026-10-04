"""3단계: 장면별 내레이션 음성 생성 + 길이 측정.

기본은 무료 edge-tts. ElevenLabs / 타입캐스트는 같은 모양의 '어댑터'로 붙어 있어서
config.yaml 또는 화면에서 엔진만 바꾸면 됩니다.
"""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Callable

import requests

from .config import UserFacingError, get_key, load_config
from .project import Project

EDGE_VOICES = {
    "ko-KR-SunHiNeural": "선희 (여성, 밝고 또렷함)",
    "ko-KR-InJoonNeural": "인준 (남성, 차분함)",
    "ko-KR-HyunsuMultilingualNeural": "현수 (남성, 자연스러움)",
}
ENGINES = {"edge": "edge-tts (무료)", "elevenlabs": "ElevenLabs (유료)", "typecast": "타입캐스트 (유료)"}


class TTSEngine:
    name = "base"

    def synthesize(self, text: str, out_path: Path) -> list[dict] | None:
        """음성 파일을 저장하고, 가능하면 문장별 타이밍 [{text,start,end}]을 돌려줍니다."""
        raise NotImplementedError

    def cache_key(self) -> str:
        return self.name


class EdgeTTS(TTSEngine):
    name = "edge"

    def __init__(self, voice: str = "ko-KR-SunHiNeural", rate: str = "+0%"):
        self.voice, self.rate = voice, rate

    def cache_key(self) -> str:
        return f"edge|{self.voice}|{self.rate}"

    def synthesize(self, text: str, out_path: Path) -> list[dict] | None:
        try:
            import edge_tts
        except ImportError as e:
            raise UserFacingError("❌ edge-tts가 설치되지 않았어요. install.bat을 다시 실행해 주세요.") from e

        async def _run():
            comm = edge_tts.Communicate(text, self.voice, rate=self.rate, boundary="SentenceBoundary")
            sentences = []
            with open(out_path, "wb") as f:
                async for chunk in comm.stream():
                    if chunk["type"] == "audio":
                        f.write(chunk["data"])
                    elif chunk["type"] == "SentenceBoundary":
                        start = chunk["offset"] / 1e7  # 100나노초 단위 → 초
                        sentences.append({"text": chunk["text"], "start": start,
                                          "end": start + chunk["duration"] / 1e7})
            return sentences

        try:
            return asyncio.run(_run())
        except Exception as e:
            out_path.unlink(missing_ok=True)
            raise UserFacingError(f"❌ edge-tts 음성 생성 실패. 인터넷 연결을 확인하고 다시 시도해 주세요. ({e})") from e


class ElevenLabsTTS(TTSEngine):
    name = "elevenlabs"

    def __init__(self, voice_id: str, model_id: str = "eleven_multilingual_v2", speed: float = 1.0,
                 api_key: str | None = None):
        if not voice_id:
            raise UserFacingError("❌ ElevenLabs Voice ID가 비어 있어요. config.yaml의 elevenlabs_voice_id 또는 화면에서 입력해 주세요.")
        self.voice_id, self.model_id, self.speed = voice_id, model_id, speed
        self.api_key = api_key or get_key("ELEVENLABS_API_KEY")

    def cache_key(self) -> str:
        return f"eleven|{self.voice_id}|{self.model_id}|{self.speed}"

    def synthesize(self, text: str, out_path: Path) -> None:
        resp = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}",
            headers={"xi-api-key": self.api_key, "Accept": "audio/mpeg"},
            json={"text": text, "model_id": self.model_id,
                  "voice_settings": {"stability": 0.5, "similarity_boost": 0.75,
                                     "speed": max(0.7, min(1.2, self.speed))}},
            timeout=120,
        )
        if resp.status_code == 401:
            raise UserFacingError("❌ ElevenLabs API 키가 올바르지 않아요. .env를 확인해 주세요.")
        if resp.status_code != 200:
            raise UserFacingError(f"❌ ElevenLabs 오류 ({resp.status_code}): {resp.text[:200]}")
        out_path.write_bytes(resp.content)
        return None


class TypecastTTS(TTSEngine):
    """타입캐스트 API 어댑터. API 형식이 바뀌면 config.yaml의 typecast_endpoint/model을 조정하세요."""
    name = "typecast"

    def __init__(self, voice_id: str, model: str = "ssfm-v21", tempo: float = 1.0,
                 endpoint: str = "https://api.typecast.ai/v1/text-to-speech", api_key: str | None = None):
        if not voice_id:
            raise UserFacingError("❌ 타입캐스트 Voice ID가 비어 있어요. config.yaml의 typecast_voice_id 또는 화면에서 입력해 주세요.")
        self.voice_id, self.model, self.tempo, self.endpoint = voice_id, model, tempo, endpoint
        self.api_key = api_key or get_key("TYPECAST_API_KEY")

    def cache_key(self) -> str:
        return f"typecast|{self.voice_id}|{self.model}|{self.tempo}"

    def synthesize(self, text: str, out_path: Path) -> None:
        resp = requests.post(
            self.endpoint,
            headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"},
            json={"voice_id": self.voice_id, "text": text, "model": self.model, "language": "kor",
                  "output": {"audio_format": "mp3", "audio_tempo": self.tempo}},
            timeout=120,
        )
        if resp.status_code in (401, 403):
            raise UserFacingError("❌ 타입캐스트 API 키가 올바르지 않아요. .env를 확인해 주세요.")
        if resp.status_code != 200 or not resp.headers.get("Content-Type", "").startswith("audio"):
            raise UserFacingError(f"❌ 타입캐스트 오류 ({resp.status_code}): {resp.text[:200]}")
        out_path.write_bytes(resp.content)
        return None


def rate_to_speed(rate: str) -> float:
    """'+10%' → 1.1"""
    try:
        return 1 + int(rate.strip().rstrip("%")) / 100
    except ValueError:
        return 1.0


def make_engine(engine: str | None = None, voice: str | None = None, rate: str | None = None,
                cfg: dict | None = None) -> TTSEngine:
    t = (cfg or load_config())["tts"]
    engine = engine or t["engine"]
    rate = rate or t["edge_rate"]
    if engine == "edge":
        return EdgeTTS(voice or t["edge_voice"], rate)
    if engine == "elevenlabs":
        return ElevenLabsTTS(voice or t["elevenlabs_voice_id"], t["elevenlabs_model"], rate_to_speed(rate))
    if engine == "typecast":
        return TypecastTTS(voice or t["typecast_voice_id"], t["typecast_model"], rate_to_speed(rate),
                           t["typecast_endpoint"])
    raise UserFacingError(f"❌ 알 수 없는 TTS 엔진: {engine}")


def audio_duration(path: Path) -> float:
    try:
        from mutagen import File as MutagenFile
        info = MutagenFile(str(path))
        if info is not None and info.info and info.info.length:
            return float(info.info.length)
    except Exception:
        pass
    from moviepy import AudioFileClip
    with AudioFileClip(str(path)) as clip:
        return float(clip.duration)


def _hash(text: str, engine_key: str) -> str:
    return hashlib.sha1(f"{engine_key}|{text}".encode("utf-8")).hexdigest()[:12]


def generate_narration(project: Project, engine: TTSEngine,
                       progress: Callable[[float, str], None] | None = None) -> dict:
    """scenes.json을 (없으면 script.json에서) 만들고 장면별 음성·길이를 기록합니다.
    내용이 바뀌지 않은 장면은 다시 만들지 않습니다."""
    script = project.load_script()
    if not script:
        raise UserFacingError("❌ 대본이 없어요. ② 대본 탭에서 먼저 대본을 만들고 저장해 주세요.")
    project.invalidate_from("tts")
    old ={s["id"]: s for s in (project.load_scenes() or {}).get("scenes", [])}
    data = {k: v for k, v in script.items() if k != "scenes"}
    data["scenes"] = []
    total = len(script["scenes"])
    for i, sc in enumerate(script["scenes"]):
        scene = dict(sc)
        text = scene["narration"].strip()
        if progress:
            progress(i / total, f"장면 {scene['id']}/{total} 음성 만드는 중…")
        if not text:
            scene.update(audio=None, duration=2.0, sentences=[], tts_hash=None)
        else:
            out = project.audio_dir / f"scene_{scene['id']:02d}.mp3"
            h = _hash(text, engine.cache_key())
            prev = old.get(scene["id"], {})
            if prev.get("tts_hash") == h and out.exists():
                scene.update(audio=prev["audio"], duration=prev["duration"],
                             sentences=prev.get("sentences", []), tts_hash=h)
            else:
                sentences = engine.synthesize(text, out) or []
                scene.update(audio=str(out.relative_to(project.path)), duration=round(audio_duration(out), 3),
                             sentences=sentences, tts_hash=h)
        # 소재 정보는 이전 결과를 유지 (키워드가 같을 때만)
        prev = old.get(scene["id"], {})
        if prev.get("media") and prev.get("visual_keywords_en") == scene.get("visual_keywords_en"):
            scene["media"] = prev["media"]
        data["scenes"].append(scene)
    project.save_scenes(data)
    project.mark_done("tts", total_seconds=round(sum(s["duration"] for s in data["scenes"]), 1))
    if progress:
        progress(1.0, "내레이션 완료")
    return data
