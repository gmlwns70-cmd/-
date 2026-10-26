"""설정(.env, config.yaml) 읽기와 친절한 한국어 오류 메시지."""
from __future__ import annotations

import copy
import os
import shutil
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = ROOT / "assets"
MY_FOOTAGE_DIR = ASSETS_DIR / "my_footage"
LICENSED_DIR = ASSETS_DIR / "licensed"
BGM_DIR = ASSETS_DIR / "bgm"
FONTS_DIR = ROOT / "fonts"
PROMPTS_DIR = ROOT / "prompts"
PROJECTS_DIR = ROOT / "projects"

ENV_PATH = ROOT / ".env"
load_dotenv(ENV_PATH)


def reload_env() -> None:
    """.env를 다시 읽어서, 키를 바꾼 뒤 새로고침(F5)만 해도 적용되게 합니다."""
    load_dotenv(ENV_PATH, override=True)


def env_file_problem() -> str | None:
    """.env 파일이 없거나 이름이 잘못 저장된 경우 안내 문구."""
    if ENV_PATH.exists():
        return None
    if (ROOT / ".env.txt").exists():
        return "⚠️ `.env.txt` 로 저장돼 있어요. 파일 이름 끝의 `.txt` 를 지워서 `.env` 로 바꿔 주세요."
    return f"⚠️ `.env` 파일이 없어요. `.env.example` 을 복사해서 이름을 `.env` 로 바꿔 주세요. (위치: {ROOT})"

DEFAULTS: dict = {
    "claude": {"model": "claude-sonnet-5-5", "effort": "high", "use_fallback": True,
               "chars_per_minute": 300},
    "research": {"region_code": "KR", "relevance_language": "ko"},
    "tts": {"engine": "edge", "edge_voice": "ko-KR-SunHiNeural", "edge_rate": "+0%",
            "elevenlabs_voice_id": "", "elevenlabs_model": "eleven_multilingual_v2",
            "typecast_voice_id": "", "typecast_model": "ssfm-v21",
            "typecast_endpoint": "https://api.typecast.ai/v1/text-to-speech"},
    "assets": {"stock_order": ["pexels", "pixabay"], "max_clips_per_scene": 4, "image_seconds": 5},
    "subtitles": {"max_chars_per_line": 18, "max_lines": 2, "font_size": 54, "stroke_width": 4,
                  "bottom_margin_pct": 10, "color": "#FFFFFF", "stroke_color": "#000000",
                  "font_file": ""},
    "render": {"fps": 30, "scene_padding": 0.35, "bgm_volume": 0.25, "bgm_duck_volume": 0.07,
               "on_screen_text_seconds": 3.5, "shorts_max_seconds": 58, "shorts_fit": "blur",
               "preset": "medium"},
}

# 키 이름 → (서비스 이름, 어디에 쓰는지, 발급 안내)
KEY_INFO = {
    "ANTHROPIC_API_KEY": ("Claude API", "대본 생성",
                          "https://console.anthropic.com → API Keys → Create Key"),
    "YOUTUBE_API_KEY": ("YouTube Data API v3", "트렌드 리서치",
                        "https://console.cloud.google.com → API 및 서비스 → 사용자 인증 정보"),
    "PEXELS_API_KEY": ("Pexels", "무료 스톡 영상·사진", "https://www.pexels.com/api/ → Your API Key"),
    "PIXABAY_API_KEY": ("Pixabay", "무료 스톡 영상·사진", "https://pixabay.com/api/docs/ (로그인 후 키 표시)"),
    "ELEVENLABS_API_KEY": ("ElevenLabs", "고품질 유료 TTS", "https://elevenlabs.io → Profile → API Keys"),
    "TYPECAST_API_KEY": ("타입캐스트", "고품질 유료 TTS", "https://typecast.ai → 개발자 API"),
}


class UserFacingError(Exception):
    """화면에 그대로 보여줘도 되는 한국어 오류."""


class MissingKeyError(UserFacingError):
    def __init__(self, key_name: str):
        service, usage, guide = KEY_INFO.get(key_name, (key_name, "", ""))
        super().__init__(
            f"❌ {service} 키가 없어요. ({usage}에 필요합니다)\n\n"
            f"해결 방법:\n"
            f"1. 프로그램 폴더의 `.env` 파일을 메모장으로 여세요.\n"
            f"2. `{key_name}=` 뒤에 키를 붙여넣고 저장하세요.\n"
            f"3. 프로그램을 껐다가 다시 켜세요. (run.bat)\n\n"
            f"키 발급: {guide}\n(자세한 방법은 README.md의 'API 키 받기'를 보세요.)"
        )
        self.key_name = key_name


def get_key(name: str, required: bool = True) -> str | None:
    value = (os.environ.get(name) or "").strip()
    if not value:
        if required:
            raise MissingKeyError(name)
        return None
    return value


def key_status() -> dict[str, bool]:
    reload_env()
    return {name: bool(get_key(name, required=False)) for name in KEY_INFO}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: Path | None = None) -> dict:
    path = path or ROOT / "config.yaml"
    if not path.exists():
        return copy.deepcopy(DEFAULTS)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise UserFacingError(
            f"❌ config.yaml 파일 형식이 잘못됐어요. 들여쓰기(띄어쓰기)나 콜론(:)을 확인해 주세요.\n세부 내용: {e}"
        ) from e
    return _deep_merge(DEFAULTS, data)


def find_ffmpeg() -> str | None:
    """시스템 ffmpeg가 없으면 imageio-ffmpeg에 들어있는 ffmpeg를 사용합니다."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None
