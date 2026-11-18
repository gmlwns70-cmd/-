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

DEFAULTS = {
    "idea": "",
    "genre": "로맨스",
    "episodes": 3,
    "seconds": 60,
    "aspect": "9:16",
    "cut_min": 3,
    "cut_max": 8,
    "visual_style": "cinematic Korean drama look, soft natural lighting, shallow depth of field, "
                    "photorealistic, 35mm film tone",
    "claude": {
        "model": "claude-opus-5-5",
        "effort": "high",
        "use_fallback": True,
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
    cfg["episodes"] = max(1, min(20, int(cfg["episodes"])))
    cfg["seconds"] = max(20, min(180, int(cfg["seconds"])))
    cfg["cut_min"] = max(2, int(cfg["cut_min"]))
    cfg["cut_max"] = max(cfg["cut_min"], int(cfg["cut_max"]))
    return cfg


def has_key(name: str) -> bool:
    """환경변수에 키가 들어 있는지만 알려줍니다(값은 절대 반환하지 않음)."""
    return bool(os.getenv(name, "").strip())


def slugify(text: str, limit: int = 30) -> str:
    text = re.sub(r"[^\w\s가-힣-]", "", text).strip()
    text = re.sub(r"\s+", "_", text)
    return text[:limit] or "drama"


def new_output_dir(title: str) -> Path:
    base = OUTPUT_DIR / f"{date.today().isoformat()}_{slugify(title)}"
    out, n = base, 2
    while out.exists():
        out = base.with_name(f"{base.name}_{n}")
        n += 1
    out.mkdir(parents=True)
    return out
