"""config.yaml + .env + 명령줄 인자를 하나의 설정으로 합칩니다.

API 키 값은 이 모듈 밖으로 내보내거나 화면에 출력하지 않습니다.
키가 '있는지 없는지'만 확인합니다.
"""
from __future__ import annotations

import copy
import os
import re
from datetime import date
from pathlib import Path

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
ASSETS_DIR = BASE_DIR / "assets"
FONTS_DIR = BASE_DIR / "fonts"

DEFAULTS = {
    "topic": "",
    "target": "자영업 사장님",
    "brand": "@my_brand",
    "cards": 15,
    "character": "30대 한국인 여성 사장님, 갈색 올림머리, 연분홍 셔츠, 베이지 앞치마",
    "claude": {
        "model": "claude-opus-5-5",
        "effort": "high",
        "use_fallback": True,
        "max_searches": 8,
    },
    "style": {
        "cover_size": 80,
        "text_size": 70,
        "illustrated_size": 64,
        "min_size": 52,
        "line_height": 1.3,
        "line_max_chars": 13,
        "line_tolerance": 1,
        "illustration_ratio": 0.4,
    },
}


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        elif v is not None:
            out[k] = v
    return out


def load_config(path: Path | None = None, overrides: dict | None = None) -> dict:
    """기본값 ← config.yaml ← 명령줄 인자 순서로 덮어씁니다."""
    load_dotenv(BASE_DIR / ".env", override=True)
    path = path or (BASE_DIR / "config.yaml")
    data = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    cfg = _merge(DEFAULTS, data)
    cfg = _merge(cfg, {k: v for k, v in (overrides or {}).items() if v not in (None, "")})
    cfg["cards"] = max(10, min(15, int(cfg["cards"])))
    return cfg


def has_key(name: str) -> bool:
    """환경변수에 키가 들어 있는지만 알려줍니다(값은 절대 반환하지 않음)."""
    return bool(os.getenv(name, "").strip())


def image_provider() -> str:
    return os.getenv("IMAGE_PROVIDER", "none").strip().lower() or "none"


def slugify(text: str, limit: int = 30) -> str:
    text = re.sub(r"[^\w\s가-힣-]", "", text).strip()
    text = re.sub(r"\s+", "_", text)
    return text[:limit] or "cardnews"


def new_output_dir(topic: str) -> Path:
    base = OUTPUT_DIR / f"{date.today().isoformat()}_{slugify(topic)}"
    out, n = base, 2
    while out.exists():
        out = base.with_name(f"{base.name}_{n}")
        n += 1
    out.mkdir(parents=True)
    return out
