"""Claude API로 ① 시리즈 설정집 → ② 회차별 컷 대본을 만듭니다."""
from __future__ import annotations

import json

from . import prompts


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


S = {"type": "string"}
I = {"type": "integer"}

CHARACTER = _obj({"id": S, "name": S, "role": S, "age": I, "personality": S,
                  "look_ko": S, "look_en": S, "voice": S})
EPISODE_OUTLINE = _obj({"no": I, "title": S, "hook": S, "summary": S, "cliffhanger": S})
BIBLE_SCHEMA = _obj({
    "title": S, "logline": S, "tone": S,
    "characters": {"type": "array", "items": CHARACTER},
    "episodes": {"type": "array", "items": EPISODE_OUTLINE},
})

LINE = _obj({"speaker": S, "line": S})
CUT = _obj({
    "no": I, "seconds": I, "location": S, "time_of_day": S,
    "characters": {"type": "array", "items": S},
    "shot": {"type": "string", "enum": ["extreme close-up", "close-up", "medium close-up",
                                         "medium shot", "over-the-shoulder", "two shot",
                                         "wide shot", "insert"]},
    "camera_move": S, "action_ko": S,
    "dialogue": {"type": "array", "items": LINE},
    "emotion": S, "sound": S,
    "video_prompt_en": S, "image_prompt_en": S, "subtitle": S,
    "transition": {"type": "string", "enum": ["cut", "dissolve", "fade_black", "flash_white", "slide"]},
})
UPLOAD = _obj({"titles": {"type": "array", "items": S}, "description": S,
              "hashtags": {"type": "array", "items": S}})
EPISODE_SCHEMA = _obj({"no": I, "title": S, "thumbnail_text": S, "thumbnail_cut": I, "upload": UPLOAD,
                        "cuts": {"type": "array", "items": CUT}})


class GenerateError(RuntimeError):
    pass


def _client():
    try:
        import anthropic
    except ImportError as e:
        raise GenerateError("anthropic 패키지가 없습니다. 'pip install -r requirements.txt' 를 먼저 실행하세요.") from e
    return anthropic.Anthropic()  # 키는 .env 의 ANTHROPIC_API_KEY 에서 자동으로 읽습니다


def _create(client, cfg: dict, **kwargs):
    """긴 응답도 끊기지 않게 스트리밍으로 받고, 안전 필터 거절 시 다른 모델로 자동 재시도합니다."""
    import anthropic
    c = cfg["claude"]
    params = dict(model=c["model"], **kwargs)
    if c.get("use_fallback", True):
        params.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    try:
        with client.beta.messages.stream(**params) as s:
            msg = s.get_final_message()
    except anthropic.AuthenticationError as e:
        raise GenerateError("Claude API 키가 올바르지 않습니다. .env 의 ANTHROPIC_API_KEY 를 확인하세요.") from e
    except anthropic.PermissionDeniedError as e:
        raise GenerateError("이 API 키로는 해당 모델을 쓸 수 없어요. 콘솔에서 결제/권한을 확인하세요.") from e
    except anthropic.NotFoundError as e:
        raise GenerateError(f"모델 '{c['model']}' 을(를) 찾을 수 없어요. config.yaml 의 claude: model 을 확인하세요.") from e
    except anthropic.BadRequestError as e:
        if "fallback" in str(e).lower() and params.pop("fallbacks", None):
            return _create(client, {**cfg, "claude": {**c, "use_fallback": False}}, **kwargs)
        raise GenerateError(f"Claude API 요청 오류: {e.message}") from e
    except anthropic.RateLimitError as e:
        raise GenerateError("요청이 너무 많습니다. 1~2분 뒤 다시 실행해 주세요.") from e
    except anthropic.APIStatusError as e:
        raise GenerateError(f"Claude 서버 오류({e.status_code}). 잠시 뒤 다시 실행해 주세요.") from e
    except anthropic.APIConnectionError as e:
        raise GenerateError("인터넷 연결을 확인해 주세요 (Claude API에 접속하지 못했습니다).") from e
    if msg.stop_reason == "refusal":
        raise GenerateError("Claude가 이 아이디어의 대본 작성을 거절했습니다. 아이디어 문장을 바꿔 보세요.")
    if msg.stop_reason == "max_tokens":
        raise GenerateError("대본이 너무 길어 중간에 끊겼습니다. 회차 길이(seconds)를 줄이거나 다시 실행해 주세요.")
    return msg


def _json(msg) -> dict:
    text = "".join(b.text for b in msg.content if b.type == "text")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise GenerateError("Claude 응답을 읽지 못했어요. 다시 실행해 주세요.") from e


# ── ① 시리즈 설정집 ───────────────────────────────────────
def make_bible(cfg: dict, client=None) -> dict:
    client = client or _client()
    user = (f"아이디어: {cfg['idea']}\n장르: {cfg['genre']}\n"
            f"회차 수: 정확히 {cfg['episodes']}회 (no 1~{cfg['episodes']})\n"
            f"회차 길이: 약 {cfg['seconds']}초의 세로 숏폼")
    msg = _create(client, cfg, system=prompts.BIBLE_SYSTEM, max_tokens=32000,
                  output_config={"effort": cfg["claude"].get("effort", "high"),
                                 "format": {"type": "json_schema", "schema": BIBLE_SCHEMA}},
                  messages=[{"role": "user", "content": user}])
    bible = _json(msg)
    bible["episodes"] = bible["episodes"][: cfg["episodes"]]
    for i, ep in enumerate(bible["episodes"], 1):
        ep["no"] = i
    return bible


# ── ② 회차별 컷 대본 ──────────────────────────────────────
def make_episode(cfg: dict, bible: dict, ep_no: int, prev_summary: str = "", client=None) -> dict:
    client = client or _client()
    outline = bible["episodes"][ep_no - 1]
    system = prompts.EPISODE_SYSTEM.format(cut_min=cfg["cut_min"], cut_max=cfg["cut_max"], aspect=cfg["aspect"])
    bible_brief = {k: bible[k] for k in ("title", "logline", "tone", "characters")}
    user = (f"설정집:\n{json.dumps(bible_brief, ensure_ascii=False)}\n\n"
            f"이번 회차 줄거리:\n{json.dumps(outline, ensure_ascii=False)}\n\n"
            + (f"지난 회차 마지막 상황: {prev_summary}\n\n" if prev_summary else "")
            + f"목표 길이: {cfg['seconds']}초. 인물 id 는 설정집의 id 만 쓰세요.")
    msg = _create(client, cfg, system=system, max_tokens=64000,
                  output_config={"effort": cfg["claude"].get("effort", "high"),
                                 "format": {"type": "json_schema", "schema": EPISODE_SCHEMA}},
                  messages=[{"role": "user", "content": user}])
    ep = _json(msg)
    ep["no"] = ep_no
    ep["title"] = ep.get("title") or outline["title"]
    for i, c in enumerate(ep["cuts"], 1):
        c["no"] = i
    return ep


def make_upload(cfg: dict, series: dict, ep: dict, client=None) -> dict:
    """예전에 만든 대본에 업로드 문구만 새로 만들어 붙입니다."""
    client = client or _client()
    bible = series["bible"]
    brief = {"series": {k: bible[k] for k in ("title", "logline", "tone")},
             "episode": {"no": ep["no"], "title": ep["title"], "total": len(series["episodes"]),
                         "summary": next((o["summary"] for o in bible["episodes"] if o["no"] == ep["no"]), ""),
                         "lines": [d["line"] for c in ep["cuts"] for d in c["dialogue"]][:20]}}
    rules = prompts.EPISODE_SYSTEM.split("- upload:")[1].split("- 세로")[0]
    msg = _create(client, cfg, system="숏폼 드라마 회차의 업로드 문구를 씁니다.\n- upload:" + rules, max_tokens=8000,
                  output_config={"effort": "medium", "format": {"type": "json_schema", "schema": UPLOAD}},
                  messages=[{"role": "user", "content": json.dumps(brief, ensure_ascii=False)}])
    return _json(msg)


def make_series(cfg: dict, client=None, log=print) -> dict:
    client = client or _client()
    log("[1/2] 시리즈 설정집 (제목·인물·회차 줄거리)")
    bible = make_bible(cfg, client)
    log(f"  · 제목: {bible['title']}  /  인물 {len(bible['characters'])}명  /  {len(bible['episodes'])}회")
    log("[2/2] 회차별 컷 대본")
    episodes, prev = [], ""
    for outline in bible["episodes"]:
        log(f"  · EP{outline['no']:02d} {outline['title']} 작성 중...")
        ep = make_episode(cfg, bible, outline["no"], prev, client)
        episodes.append(ep)
        prev = outline["cliffhanger"]
    return {"bible": bible, "episodes": episodes}
