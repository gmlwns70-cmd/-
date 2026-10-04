"""2단계: Claude API로 영상 대본(JSON) 생성."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .config import PROMPTS_DIR, UserFacingError, get_key, load_config

TONES = ["정보형", "감성형", "유머형"]
SCENE_TYPES = ["hook", "intro", "body", "outro"]

SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "thumbnail_text": {"type": "string"},
        "description": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "type": {"type": "string", "enum": SCENE_TYPES},
                    "narration": {"type": "string"},
                    "on_screen_text": {"type": "string"},
                    "visual_keywords_en": {"type": "array", "items": {"type": "string"}},
                    "prefer_my_footage": {"type": "boolean"},
                    "shorts": {"type": "boolean"},
                },
                "required": ["id", "type", "narration", "on_screen_text", "visual_keywords_en",
                             "prefer_my_footage", "shorts"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "thumbnail_text", "description", "tags", "scenes"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You are a Korean YouTube scriptwriter. Write only original content; never copy, translate, "
    "or paraphrase existing videos or articles. Reply with the JSON object only."
)


def format_assets(assets: list[dict]) -> str:
    if not assets:
        return "(없음 — 모든 장면에서 prefer_my_footage를 false로 하세요)"
    lines = []
    for a in assets[:80]:
        memo = f" — {a['memo']}" if a.get("memo") else ""
        lines.append(f"- {a['file']}{memo}")
    return "\n".join(lines)


def build_prompt(topic: str, minutes: float, tone: str, assets: list[dict],
                 template_path: Path | None = None, chars_per_minute: int = 300) -> str:
    template_path = template_path or PROMPTS_DIR / "script_prompt.md"
    if not template_path.exists():
        raise UserFacingError(f"❌ 프롬프트 파일이 없어요: {template_path}")
    template = template_path.read_text(encoding="utf-8")
    template = re.sub(r"<!--.*?-->", "", template, flags=re.S).strip()
    values = {
        "topic": topic, "minutes": f"{minutes:g}", "tone": tone,
        "target_chars": str(int(minutes * chars_per_minute)),
        "scene_count": str(max(4, round(minutes * 60 / 16))),
        "my_assets": format_assets(assets),
    }
    for k, v in values.items():
        template = template.replace("{{" + k + "}}", v)
    return template


def _parse_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if m:
            return json.loads(m.group(0))
        raise


def normalize_script(data: dict) -> dict:
    """형식을 검사하고 빠진 값을 채웁니다. (화면에서 수정한 대본에도 사용)"""
    if not isinstance(data, dict) or not isinstance(data.get("scenes"), list) or not data["scenes"]:
        raise UserFacingError("❌ 대본 형식이 올바르지 않아요. (scenes 목록이 비어 있음)")
    tags = data.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    out = {
        "title": str(data.get("title", "")).strip(),
        "thumbnail_text": str(data.get("thumbnail_text", "")).strip(),
        "description": str(data.get("description", "")).strip(),
        "tags": [str(t).strip() for t in tags if str(t).strip()],
        "scenes": [],
    }
    for i, sc in enumerate(data["scenes"], start=1):
        kw = sc.get("visual_keywords_en") or []
        if isinstance(kw, str):
            kw = [k.strip() for k in kw.split(",")]
        stype = str(sc.get("type", "body")).strip().lower()
        out["scenes"].append({
            "id": i,
            "type": stype if stype in SCENE_TYPES else "body",
            "narration": str(sc.get("narration") or "").strip(),
            "on_screen_text": str(sc.get("on_screen_text") or "").strip(),
            "visual_keywords_en": [str(k).strip() for k in kw if str(k).strip()],
            "prefer_my_footage": bool(sc.get("prefer_my_footage", False)),
            "shorts": bool(sc.get("shorts", False)),
        })
    out["scenes"] = [s for s in out["scenes"] if s["narration"] or s["on_screen_text"]]
    for i, s in enumerate(out["scenes"], start=1):
        s["id"] = i
    if not out["scenes"]:
        raise UserFacingError("❌ 내레이션이 있는 장면이 하나도 없어요.")
    return out


def generate_script(topic: str, minutes: float = 8, tone: str = "정보형",
                    assets: list[dict] | None = None, client=None, cfg: dict | None = None) -> dict:
    if not topic.strip():
        raise UserFacingError("❌ 영상 주제를 입력해 주세요.")
    cfg = cfg or load_config()
    ccfg = cfg["claude"]
    if assets is None:
        from .assets import scan_local_assets
        assets = [{"file": a.path.name, "memo": a.memo} for a in scan_local_assets()]
    prompt = build_prompt(topic, minutes, tone, assets, chars_per_minute=int(ccfg["chars_per_minute"]))

    import anthropic

    if client is None:
        client = anthropic.Anthropic(api_key=get_key("ANTHROPIC_API_KEY"))
    kwargs = dict(
        model=ccfg["model"],
        max_tokens=64000,
        system=SYSTEM_PROMPT,
        thinking={"type": "adaptive"},
        output_config={"effort": ccfg["effort"],
                       "format": {"type": "json_schema", "schema": SCRIPT_SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )
    if ccfg.get("use_fallback", True):
        kwargs.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")

    try:
        with client.beta.messages.stream(**kwargs) as stream:
            message = stream.get_final_message()
    except anthropic.AuthenticationError as e:
        raise UserFacingError("❌ Claude API 키가 올바르지 않아요. .env 파일의 ANTHROPIC_API_KEY를 확인해 주세요.") from e
    except anthropic.PermissionDeniedError as e:
        raise UserFacingError("❌ 이 API 키로는 해당 모델을 쓸 수 없어요. 결제 정보 등록 여부와 config.yaml의 모델 이름을 확인해 주세요.") from e
    except anthropic.NotFoundError as e:
        raise UserFacingError(f"❌ 모델 이름 '{ccfg['model']}'을(를) 찾을 수 없어요. config.yaml의 claude: model 값을 확인해 주세요.") from e
    except anthropic.RateLimitError as e:
        raise UserFacingError("❌ 요청이 너무 많거나 크레딧이 부족해요. 잠시 후 다시 시도하거나 콘솔에서 잔액을 확인해 주세요.") from e
    except anthropic.BadRequestError as e:
        raise UserFacingError(f"❌ Claude API가 요청을 거부했어요: {e.message}") from e
    except anthropic.APIStatusError as e:
        raise UserFacingError(f"❌ Claude 서버 오류({e.status_code})예요. 잠시 후 다시 시도해 주세요.") from e
    except anthropic.APIConnectionError as e:
        raise UserFacingError("❌ 인터넷 연결을 확인해 주세요. (Claude API 접속 실패)") from e

    if message.stop_reason == "refusal":
        raise UserFacingError("❌ Claude가 이 주제의 대본 작성을 거절했어요. 주제를 바꾸거나 표현을 순화해 보세요.")
    if message.stop_reason == "max_tokens":
        raise UserFacingError("❌ 대본이 너무 길어서 중간에 잘렸어요. 목표 길이(분)를 줄여서 다시 시도해 주세요.")
    text = "".join(b.text for b in message.content if b.type == "text")
    try:
        data = _parse_json(text)
    except json.JSONDecodeError as e:
        raise UserFacingError("❌ 대본 결과를 읽지 못했어요. 한 번 더 '대본 생성'을 눌러 주세요.") from e
    return normalize_script(data)


# ---------- 화면 편집용 변환 (st.data_editor) ----------
EDITOR_COLUMNS = ["id", "type", "narration", "on_screen_text", "visual_keywords_en", "prefer_my_footage", "shorts"]


def scenes_to_rows(scenes: list[dict]) -> list[dict]:
    rows = []
    for s in scenes:
        row = {k: s.get(k) for k in EDITOR_COLUMNS}
        row["visual_keywords_en"] = ", ".join(s.get("visual_keywords_en", []))
        rows.append(row)
    return rows


def clean_cell(v):
    # 표에서 빈 칸은 NaN/None으로 들어옵니다
    return "" if v is None or (isinstance(v, float) and v != v) else v


def rows_to_scenes(rows: list[dict]) -> list[dict]:
    scenes = []
    for r in rows:
        r = {k: clean_cell(v) for k, v in r.items()}
        kw = r.get("visual_keywords_en") or ""
        scenes.append({**r, "visual_keywords_en": [k.strip() for k in str(kw).split(",") if k.strip()]})
    return scenes


def estimate_minutes(script: dict, chars_per_minute: int = 300) -> float:
    total = sum(len(s["narration"]) for s in script.get("scenes", []))
    return total / chars_per_minute
