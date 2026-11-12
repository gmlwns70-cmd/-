"""1~2단계: Claude API로 자료 조사(웹 검색) → 원고 JSON 생성 → 수치 검증/교정."""
from __future__ import annotations

import json
import re

from . import factcheck, prompts

LINE = {
    "type": "object",
    "properties": {"text": {"type": "string"}, "highlight": {"type": "boolean"}},
    "required": ["text", "highlight"],
    "additionalProperties": False,
}
SOURCE = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "url": {"type": "string"}},
    "required": ["name", "url"],
    "additionalProperties": False,
}
CARD = {
    "type": "object",
    "properties": {
        "no": {"type": "integer"},
        "role": {"type": "string"},
        "type": {"type": "string", "enum": ["cover", "illustrated", "text"]},
        "lines": {"type": "array", "items": LINE},
        "image_prompt": {"type": "string"},
        "emotion": {"type": "string"},
        "source": SOURCE,
        "verify_needed": {"type": "boolean"},
    },
    "required": ["no", "role", "type", "lines", "image_prompt", "emotion", "source", "verify_needed"],
    "additionalProperties": False,
}
SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "cards": {"type": "array", "items": CARD},
        "caption": {
            "type": "object",
            "properties": {
                "body": {"type": "string"},
                "cta": {"type": "string"},
                "hashtags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["body", "cta", "hashtags"],
            "additionalProperties": False,
        },
    },
    "required": ["cards", "caption"],
    "additionalProperties": False,
}
REPAIR_SCHEMA = {
    "type": "object",
    "properties": {"cards": {"type": "array", "items": {
        "type": "object",
        "properties": {"no": {"type": "integer"}, "lines": {"type": "array", "items": LINE}},
        "required": ["no", "lines"], "additionalProperties": False}}},
    "required": ["cards"],
    "additionalProperties": False,
}


class ScriptError(RuntimeError):
    pass


def _client():
    try:
        import anthropic
    except ImportError as e:
        raise ScriptError("anthropic 패키지가 없습니다. 'pip install -r requirements.txt' 를 먼저 실행하세요.") from e
    return anthropic.Anthropic()  # 키는 .env 의 ANTHROPIC_API_KEY 에서 자동으로 읽습니다


def explain_bad_request(msg: str) -> str:
    """API가 거절한 이유를 쉬운 한국어로 바꿉니다."""
    low = msg.lower()
    if "credit balance" in low or "billing" in low:
        return ("Claude API 충전 금액(크레딧)이 부족해요.\n"
                "   → https://console.anthropic.com 에 로그인 → Billing(결제) 에서 충전한 뒤 다시 눌러 주세요.\n"
                "   (claude.ai Pro 구독과 API 요금은 따로예요)")
    if "model" in low and ("not found" in low or "does not exist" in low or "access" in low):
        return "이 API 키로는 설정된 모델을 쓸 수 없어요. config.yaml 의 claude.model 을 확인해 주세요.\n   원문: " + msg
    if "web_search" in low or "web search" in low:
        return ("이 API 계정에서 웹 검색 기능이 꺼져 있어요.\n"
                "   → console.anthropic.com 의 설정(Privacy/Features)에서 Web search 를 켜 주세요.\n   원문: " + msg)
    return "Claude API가 요청을 거절했어요.\n   원문: " + msg


def _create(client, cfg: dict, stream: bool = False, **kwargs):
    """요청이 안전 필터에 거절되면 다른 모델로 자동 재시도(fallbacks)하도록 보냅니다."""
    import anthropic
    c = cfg["claude"]
    params = dict(model=c["model"], **kwargs)
    if c.get("use_fallback", True):
        params.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    try:
        if stream:
            with client.beta.messages.stream(**params) as s:
                msg = s.get_final_message()
        else:
            msg = client.beta.messages.create(**params)
    except anthropic.AuthenticationError as e:
        raise ScriptError("Claude API 키가 올바르지 않습니다. .env 의 ANTHROPIC_API_KEY 를 확인하세요.") from e
    except anthropic.BadRequestError as e:
        if "fallback" in str(e).lower() and params.pop("fallbacks", None):
            params.pop("betas", None)
            return _create(client, {**cfg, "claude": {**c, "use_fallback": False}}, stream, **kwargs)
        raise ScriptError(explain_bad_request(str(e))) from e
    except anthropic.RateLimitError as e:
        raise ScriptError("요청이 너무 많습니다. 1~2분 뒤 다시 실행해 주세요.") from e
    except anthropic.APIConnectionError as e:
        raise ScriptError("인터넷 연결을 확인해 주세요 (Claude API에 접속하지 못했습니다).") from e
    if msg.stop_reason == "refusal":
        raise ScriptError("Claude가 이 주제의 원고 작성을 거절했습니다. 주제 문장을 바꿔 보세요.")
    return msg


def _text(msg) -> str:
    return "".join(b.text for b in msg.content if b.type == "text")


# ── 1) 자료 조사 ─────────────────────────────────────────
def research(cfg: dict, client=None) -> list[dict]:
    client = client or _client()
    tools = [{
        "type": "web_search_20260209", "name": "web_search",
        "max_uses": int(cfg["claude"].get("max_searches", 8)),
        "user_location": {"type": "approximate", "country": "KR", "timezone": "Asia/Seoul"},
    }]
    user = (f"주제: {cfg['topic']}\n타깃: {cfg['target']}\n\n"
            "이 주제의 '근거 데이터' 카드 3장에 쓸 수 있는 실제 통계·조사 결과를 4~8개 찾아 주세요. "
            "한국 자료를 우선하고, 없으면 해외 자료도 좋아요.")
    messages = [{"role": "user", "content": user}]
    found_urls: set[str] = set()
    msg = None
    for _ in range(5):  # pause_turn 이어받기 최대 5번
        msg = _create(client, cfg, system=prompts.RESEARCH_SYSTEM, max_tokens=16000,
                      output_config={"effort": cfg["claude"].get("effort", "high")},
                      tools=tools, messages=messages)
        found_urls |= _collect_urls(msg)
        if msg.stop_reason != "pause_turn":
            break
        messages = [{"role": "user", "content": user}, {"role": "assistant", "content": msg.content}]

    facts = _parse_json_array(_text(msg))
    allowed = {factcheck.norm_url(u) for u in found_urls}
    verified, dropped = [], 0
    for f in facts:
        if not isinstance(f, dict) or not f.get("url"):
            continue
        # 실제 검색 결과에 나온 URL만 인정 (지어낸 링크 차단)
        if factcheck.norm_url(f["url"]) in allowed:
            verified.append({k: str(f.get(k, "")) for k in ("claim", "figure", "publisher", "title", "date", "url")})
        else:
            dropped += 1
    for i, f in enumerate(verified, 1):
        f["id"] = f"S{i}"
    print(f"  · 검증된 자료 {len(verified)}개" + (f" (검색 결과에 없던 링크 {dropped}개는 버림)" if dropped else ""))
    return verified


def _collect_urls(msg) -> set[str]:
    urls = set()
    for b in msg.content:
        if b.type == "web_search_tool_result" and isinstance(getattr(b, "content", None), list):
            urls |= {r.url for r in b.content if getattr(r, "url", None)}
        for c in getattr(b, "citations", None) or []:
            if getattr(c, "url", None):
                urls.add(c.url)
    return urls


def _parse_json_array(text: str) -> list:
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


# ── 2) 원고 작성 ─────────────────────────────────────────
def write_script(cfg: dict, facts: list[dict], client=None) -> dict:
    client = client or _client()
    fact_lines = "\n".join(
        f"- [{f['id']}] {f['claim']} (숫자: {f['figure']}) — name: {f['publisher']}, url: {f['url']}, 날짜: {f['date']}"
        for f in facts) or "- (검증된 자료 없음: 숫자를 쓰지 말고 데이터 카드는 verify_needed=true)"
    user = (f"주제: {cfg['topic']}\n타깃: {cfg['target']}\n브랜드: {cfg['brand']}\n"
            f"카드 장수: 정확히 {cfg['cards']}장 (no 1~{cfg['cards']})\n"
            f"고정 캐릭터: {cfg['character']}\n\n검증된 자료:\n{fact_lines}")
    msg = _create(client, cfg, stream=True, system=prompts.SCRIPT_SYSTEM, max_tokens=32000,
                  output_config={"effort": cfg["claude"].get("effort", "high"),
                                 "format": {"type": "json_schema", "schema": SCRIPT_SCHEMA}},
                  messages=[{"role": "user", "content": user}])
    if msg.stop_reason == "max_tokens":
        raise ScriptError("원고가 너무 길어 중간에 끊겼습니다. 다시 실행해 주세요.")
    data = json.loads(_text(msg))
    cards = data["cards"][: cfg["cards"]]
    for i, c in enumerate(cards, 1):
        c["no"] = i
    data["cards"] = cards
    return data


def repair_numbers(cfg: dict, script: dict, facts: list[dict], client=None) -> None:
    """검증 안 된 숫자가 있으면 숫자 없이 다시 쓰게 하고, 그래도 남으면 강제로 뺍니다."""
    problems = factcheck.verify_cards(script, facts)
    if not problems:
        return
    print(f"  · 출처와 맞지 않는 숫자 발견: {', '.join(str(p['no']) for p in problems)}번 카드 → 숫자 없이 다시 쓰는 중")
    nos = {p["no"] for p in problems}
    bad = [{"no": c["no"], "lines": c["lines"]} for c in script["cards"] if c["no"] in nos]
    try:
        client = client or _client()
        msg = _create(client, cfg, system=prompts.REPAIR_SYSTEM, max_tokens=8000,
                      output_config={"effort": "medium", "format": {"type": "json_schema", "schema": REPAIR_SCHEMA}},
                      messages=[{"role": "user", "content": json.dumps(bad, ensure_ascii=False)}])
        fixed = {c["no"]: c["lines"] for c in json.loads(_text(msg))["cards"]}
        for c in script["cards"]:
            if c["no"] in fixed:
                c["lines"] = fixed[c["no"]]
                c["source"] = {"name": "", "url": ""}
                c["verify_needed"] = True
    except ScriptError as e:
        print(f"  ⚠ 자동 교정 실패({e}) → 숫자가 든 줄을 빼겠습니다")
    still = {p["no"] for p in factcheck.verify_cards(script, facts)}
    factcheck.strip_unverified(script, still)


# ── 카드 종류 배치 (약 40% 일러스트, 교차 배치) ─────────────
def assign_types(cards: list[dict], ratio: float = 0.4) -> None:
    n = len(cards)
    want = max(0, round(n * ratio) - 1)  # 표지 1장 포함해서 약 40%
    candidates = list(range(2, n + 1, 2))  # 짝수 장에만 → 텍스트 카드와 번갈아 나옴
    if want >= len(candidates):
        picks = set(candidates)
    elif want == 0:
        picks = set()
    else:
        step = (len(candidates) - 1) / max(1, want - 1) if want > 1 else 0
        picks = {candidates[round(i * step)] for i in range(want)}
    for c in cards:
        c["type"] = "cover" if c["no"] == 1 else ("illustrated" if c["no"] in picks else "text")
