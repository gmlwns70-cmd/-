"""3단계: 일러스트 생성 (어댑터 구조).

.env 의 IMAGE_PROVIDER 로 고릅니다: openai / gemini
- 첫 생성 이미지를 images/reference.png 로 저장하고, 이후 생성 때마다 참조로 넣어 캐릭터를 유지합니다.
- 참조 이미지를 지원하지 않는 경우에도 같은 캐릭터 설명문을 매번 넣습니다.
- API 키는 환경변수에서만 읽고, 코드·로그에 출력하지 않습니다.
"""
from __future__ import annotations

import base64
import io
import os
from pathlib import Path

from PIL import Image

STYLE = (
    "Korean webtoon-style semi-realistic illustration, clean pen linework, warm watercolor coloring. "
    "Draw ONLY the character and props — no background, no floor, no scenery; "
    "plain white background so the edges blend softly into paper. "
    "No text, no letters, no watermark, no real brand logos. "
    "Original character design; do not imitate any existing artist, account or copyrighted character."
)
EMOTION_EN = {"당황": "flustered, surprised", "기대": "hopeful, expectant", "걱정": "worried",
              "고민": "thoughtful, pondering", "미소": "gentle smile"}


def build_prompt(card: dict, character: str) -> str:
    emo = card.get("emotion", "")
    return (f"{STYLE}\nFixed character (keep identical in every image): {character}.\n"
            f"Emotion: {EMOTION_EN.get(emo, emo)}.\nScene: {card.get('image_prompt', '')}")


class ImageAdapter:
    name = "base"
    supports_reference = False

    def generate(self, prompt: str, reference: Path | None) -> Image.Image:
        raise NotImplementedError


class OpenAIAdapter(ImageAdapter):
    name = "openai"
    supports_reference = True

    def __init__(self):
        from openai import OpenAI
        self.client = OpenAI()  # OPENAI_API_KEY 환경변수에서 자동으로 읽음
        self.model = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")

    def generate(self, prompt, reference):
        if reference and reference.exists():
            with open(reference, "rb") as f:
                r = self.client.images.edit(model=self.model, image=[f], prompt=prompt +
                                            "\nUse the reference image only to keep the same character.",
                                            size="1024x1536")
        else:
            r = self.client.images.generate(model=self.model, prompt=prompt, size="1024x1536")
        return Image.open(io.BytesIO(base64.b64decode(r.data[0].b64_json))).convert("RGBA")


class GeminiAdapter(ImageAdapter):
    name = "gemini"
    supports_reference = True

    def __init__(self):
        from google import genai
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY") or None)
        self.model = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")

    def generate(self, prompt, reference):
        contents = [prompt + "\nPortrait 4:5 composition."]
        if reference and reference.exists():
            contents = [Image.open(reference), "Keep exactly the same character as this reference image.\n" + contents[0]]
        r = self.client.models.generate_content(model=self.model, contents=contents)
        for part in r.candidates[0].content.parts:
            if getattr(part, "inline_data", None) and part.inline_data.data:
                return Image.open(io.BytesIO(part.inline_data.data)).convert("RGBA")
        raise RuntimeError("Gemini 응답에 이미지가 없습니다")


ADAPTERS = {"openai": (OpenAIAdapter, "OPENAI_API_KEY"), "gemini": (GeminiAdapter, "GEMINI_API_KEY")}


def get_adapter(provider: str) -> ImageAdapter:
    if provider not in ADAPTERS:
        raise RuntimeError(f"IMAGE_PROVIDER 값 '{provider}' 를 모르겠어요 (openai / gemini / none 중 하나)")
    cls, key = ADAPTERS[provider]
    if not os.getenv(key, "").strip():
        raise RuntimeError(f".env 에 {key} 가 없어요")
    try:
        return cls()
    except ImportError as e:
        raise RuntimeError(f"{provider} 패키지가 없어요. 'pip install -r requirements.txt' 를 실행하세요") from e


def generate_all(out_dir: Path, script: dict, cfg: dict, provider: str, force: bool = False) -> None:
    adapter = get_adapter(provider)
    img_dir = Path(out_dir) / "images"
    img_dir.mkdir(exist_ok=True)
    ref = img_dir / "reference.png"
    character = script.get("character") or cfg["character"]
    targets = [c for c in script["cards"] if c.get("type") in ("cover", "illustrated")]
    for card in targets:
        path = img_dir / f"card_{card['no']:02d}.png"
        if path.exists() and not force:
            continue
        print(f"  · {card['no']}번 카드 일러스트 생성 중 ({adapter.name}, 감정: {card.get('emotion', '-')})")
        try:
            img = adapter.generate(build_prompt(card, character), ref if ref.exists() else None)
        except Exception as e:
            print(f"    ⚠ 실패: {type(e).__name__} → 이 카드는 텍스트 레이아웃으로 만들어요")
            continue
        img.save(path)
        if not ref.exists():
            img.save(ref)  # 첫 이미지를 캐릭터 기준으로 저장
