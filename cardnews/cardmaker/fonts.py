"""Pretendard ExtraBold 폰트를 자동으로 내려받습니다. (SIL Open Font License 1.1)

출처: https://github.com/orioncactus/pretendard
"""
from __future__ import annotations

from pathlib import Path

import requests

from .settings import FONTS_DIR

FONT_NAME = "Pretendard-ExtraBold.otf"
FONT_URLS = [
    "https://raw.githubusercontent.com/orioncactus/pretendard/main/packages/pretendard/dist/public/static/Pretendard-ExtraBold.otf",
    "https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/public/static/Pretendard-ExtraBold.otf",
]


def ensure_font(fonts_dir: Path = FONTS_DIR) -> Path:
    path = fonts_dir / FONT_NAME
    if path.exists() and path.stat().st_size > 100_000:
        return path
    fonts_dir.mkdir(parents=True, exist_ok=True)
    errors = []
    for url in FONT_URLS:
        try:
            print(f"  · 폰트 내려받는 중: {FONT_NAME}")
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            if len(r.content) < 100_000:
                raise ValueError("파일이 너무 작습니다")
            path.write_bytes(r.content)
            return path
        except Exception as e:  # 다음 주소로 재시도
            errors.append(f"{url.split('/')[2]}: {e}")
    raise RuntimeError(
        "Pretendard 폰트를 내려받지 못했습니다.\n"
        "  https://github.com/orioncactus/pretendard/releases 에서 직접 받아\n"
        f"  {FONT_NAME} 파일을 {fonts_dir} 폴더에 넣어 주세요.\n  (" + " / ".join(errors) + ")"
    )
