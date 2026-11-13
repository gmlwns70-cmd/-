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
        self.model = os.getenv("GEMINI_IMAGE_MODEL", "").strip() or "gemini-2.5-flash-image"

    def _config(self):
        try:
            from google.genai import types
            return types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(aspect_ratio="4:5"))
        except Exception:  # 오래된 버전이면 기본 설정으로
            return None

    def generate(self, prompt, reference):
        contents = [prompt + "\nPortrait 4:5 composition."]
        if reference and reference.exists():
            contents = [Image.open(reference), "Keep exactly the same character as this reference image.\n" + contents[0]]
        cfg = self._config()
        r = self.client.models.generate_content(model=self.model, contents=contents, **({"config": cfg} if cfg else {}))
        if not getattr(r, "candidates", None):
            reason = getattr(getattr(r, "prompt_feedback", None), "block_reason", None)
            raise RuntimeError(f"NO_IMAGE: Gemini가 그림을 주지 않았어요 (차단 사유: {reason or '알 수 없음'})")
        for cand in r.candidates:
            for part in (getattr(cand.content, "parts", None) or []):
                if getattr(part, "inline_data", None) and part.inline_data.data:
                    return Image.open(io.BytesIO(part.inline_data.data)).convert("RGBA")
        finish = getattr(r.candidates[0], "finish_reason", None)
        raise RuntimeError(f"NO_IMAGE: Gemini 응답에 그림이 없어요 (종료 사유: {finish})")


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


def explain_image_error(e: Exception) -> str:
    """이미지 API 오류를 쉬운 한국어로 바꿉니다."""
    raw = f"{type(e).__name__}: {e}"
    low = raw.lower()
    if isinstance(e, ImportError) or "no module named" in low:
        return "그림용 부품이 설치되지 않았어요 → run_dashboard.bat 을 다시 실행하거나 'pip install -r requirements.txt' 를 해 주세요."
    if "api_key_invalid" in low or "api key not valid" in low or "incorrect api key" in low or "401" in low:
        return "API 키가 올바르지 않아요 → .env 의 키를 다시 복사해 넣어 주세요."
    if "limit: 0" in low or "free_tier" in low or "free tier" in low:
        return ("무료 키로는 이 모델의 그림 만들기를 쓸 수 없어요 → Google AI Studio(aistudio.google.com) → "
                "API 키 화면에서 결제(Billing)를 연결한 뒤 다시 시도하세요.")
    if "resource_exhausted" in low or "429" in low or "quota" in low or "insufficient_quota" in low:
        return "사용 한도(할당량)를 넘었어요 → 잠시 뒤 다시 하거나, 결제/한도 설정을 확인해 주세요."
    if "billing" in low:
        return "결제 설정이 필요해요 → 이미지 API 사이트에서 결제 수단을 연결해 주세요."
    if "must be verified" in low or "organization" in low and "verif" in low:
        return "OpenAI 이미지 모델은 조직 인증(Verify organization)이 필요해요 → platform.openai.com 설정에서 인증해 주세요."
    if "not_found" in low or "404" in low or "is not found" in low:
        return "그림 모델 이름을 찾을 수 없어요 → .env 의 GEMINI_IMAGE_MODEL 을 비우거나 gemini-2.5-flash-image 로 바꿔 주세요."
    if "permission_denied" in low or "403" in low:
        return "이 키로는 그림 기능을 쓸 권한이 없어요 → 키를 만든 Google 프로젝트에서 Generative Language API 사용 설정을 확인해 주세요."
    if "location" in low and "not supported" in low:
        return "지금 위치(국가)에서는 이 이미지 API를 쓸 수 없다고 해요."
    if "no_image" in low or "safety" in low or "blocked" in low:
        return "안전 필터 등으로 그림이 만들어지지 않았어요 → 다시 시도하면 될 때가 많아요."
    return "알 수 없는 오류 → " + raw[:300]


def generate_all(out_dir: Path, script: dict, cfg: dict, provider: str, force: bool = False) -> dict:
    """일러스트를 만들고 결과를 돌려줍니다: {"ok": n, "failed": n, "errors": [...]}.
    실패 이유는 images/errors.txt 에도 남겨 대시보드에서 볼 수 있게 합니다."""
    img_dir = Path(out_dir) / "images"
    img_dir.mkdir(exist_ok=True)
    err_file = img_dir / "errors.txt"
    result = {"ok": 0, "failed": 0, "errors": []}
    try:
        adapter = get_adapter(provider)
    except Exception as e:
        msg = str(e) if isinstance(e, RuntimeError) else explain_image_error(e)
        err_file.write_text(msg + "\n", encoding="utf-8")
        raise RuntimeError(msg) from e
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
            msg = explain_image_error(e)
            print(f"    ⚠ 실패: {msg}")
            result["failed"] += 1
            result["errors"].append(f"{card['no']}번 카드: {msg}")
            if result["failed"] >= 2 and result["ok"] == 0:  # 계속 실패하면 같은 이유일 가능성이 커서 멈춤
                print("    → 연속으로 실패해서 나머지 그림은 건너뛸게요. 위 이유를 해결한 뒤 '일러스트 다시 만들기'를 눌러 주세요.")
                break
            continue
        img.save(path)
        result["ok"] += 1
        if not ref.exists():
            img.save(ref)  # 첫 이미지를 캐릭터 기준으로 저장
    if result["errors"]:
        err_file.write_text("\n".join(result["errors"]) + "\n", encoding="utf-8")
    elif err_file.exists():
        err_file.unlink()
    print(f"  · 일러스트 결과: 성공 {result['ok']}장, 실패 {result['failed']}장")
    return result


def test_connection(provider: str) -> tuple[bool, str]:
    """작은 그림 하나를 만들어 이미지 API가 되는지 확인합니다."""
    try:
        adapter = get_adapter(provider)
    except Exception as e:
        return False, str(e)
    try:
        adapter.generate(STYLE + "\nScene: a single red apple on a plain white background.", None)
        return True, f"{adapter.name} 그림 만들기가 잘 돼요 ✅"
    except Exception as e:
        return False, explain_image_error(e)
