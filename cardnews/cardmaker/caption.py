"""5단계: caption.txt 만들기 (본문 + 저장·공유 유도 + 해시태그 15개)."""
from __future__ import annotations

import re
from pathlib import Path


def clean_hashtags(tags: list[str], want: int = 15) -> list[str]:
    out = []
    for t in tags:
        t = "#" + re.sub(r"[\s#]+", "", str(t))
        if len(t) > 1 and t not in out:
            out.append(t)
    return out[:want]


def write_caption(path: Path, script: dict) -> str:
    cap = script.get("caption") or {}
    tags = clean_hashtags(cap.get("hashtags", []))
    cap["hashtags"] = tags
    text = f"{cap.get('body', '').strip()}\n\n{cap.get('cta', '').strip()}\n\n{' '.join(tags)}\n"
    path.write_text(text, encoding="utf-8")
    return text
