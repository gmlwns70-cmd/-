"""Claude 대화창(claude.ai) ↔ 프로그램 연결.

1) build_prompt : 대화창에 붙여넣을 요청문을 만듭니다. (API 키 불필요)
2) import_text  : 대화창 답변(JSON)을 읽어 series.json 형식으로 정리합니다.

대화창 답변은 사람이 복사해 오므로 형식이 조금 어긋나도 최대한 살려서 읽습니다.
"""
from __future__ import annotations

import copy
import json
import re

from . import prompts

# ── 1) 요청문 ───────────────────────────────────────────
EXAMPLE = {
    "bible": {
        "title": "우산은 하나뿐",
        "logline": "비 오는 날마다 같은 정류장에서 마주치는 두 사람, 우산 하나를 둘러싼 오해가 설렘으로 바뀐다.",
        "tone": "잔잔하고 설레는 현실 로맨스",
        "characters": [
            {"id": "haeun", "name": "한하은", "role": "주인공, 꽃집 사장", "age": 28,
             "personality": "씩씩하지만 연애에는 서툴다", "look_ko": "어깨 길이 갈색 단발, 노란 레인코트",
             "look_en": "a 28-year-old Korean woman with shoulder-length brown bob hair, round eyes, "
                        "wearing a bright yellow raincoat over a cream knit sweater",
             "voice": "밝은 20대 후반 여성"},
        ],
        "episodes": [{"no": 1, "title": "그 우산, 제 건데요", "hook": "두 손이 같은 우산 손잡이를 잡는다",
                      "summary": "하은은 도준이 자기 우산을 가져가려 한다고 오해한다.",
                      "cliffhanger": "우산 안쪽 이름표는 도준의 것이었다"}],
    },
    "episodes": [{
        "no": 1, "title": "그 우산, 제 건데요",
        "thumbnail_text": "우산 하나에\n심장이 철렁", "thumbnail_cut": 1,
        "upload": {"titles": ["제목 후보1", "제목 후보2", "제목 후보3"],
                   "description": "소개 2~3문장. 마지막은 댓글 유도 질문?",
                   "hashtags": ["로맨스", "설렘주의", "비오는날"]},
        "cuts": [{
            "no": 1, "seconds": 5, "location": "bus stop", "time_of_day": "rainy evening",
            "characters": ["haeun"], "shot": "close-up", "camera_move": "slow push-in",
            "action_ko": "하은이 우산 손잡이를 꽉 잡는다",
            "dialogue": [{"speaker": "haeun", "line": "그 우산, 제 건데요."}],
            "emotion": "annoyed", "sound": "빗소리",
            "video_prompt_en": "haeun grips an umbrella handle tightly, rain pouring behind her",
            "image_prompt_en": "haeun holding an umbrella handle at a rainy bus stop",
            "subtitle": "그 우산, 제 건데요.", "transition": "cut",
        }],
    }],
}


def build_prompt(cfg: dict, idea: str = "") -> str:
    episode_rules = prompts.EPISODE_SYSTEM.format(cut_min=cfg["cut_min"], cut_max=cfg["cut_max"],
                                                  aspect=cfg["aspect"])
    idea_line = idea.strip() or "(여기에 한 줄 아이디어를 적어 주세요)"
    return f"""아래 조건으로 세로 숏폼 드라마 대본을 써 주세요. 결과는 제 편집 프로그램이 읽을 수 있도록 **JSON 코드블록 하나로만** 답해 주세요.

■ 아이디어: {idea_line}
■ 장르: {cfg['genre']}
■ 회차 수: {cfg['episodes']}회{'' if cfg['episodes'] == 1 else f" (no 1~{cfg['episodes']})"}
■ 회당 길이: 약 {cfg['seconds']}초

[시리즈 설정 규칙]
{prompts.BIBLE_SYSTEM.strip()}

[회차 대본 규칙]
{episode_rules.strip()}

[출력 형식]
- 아래 예시와 **똑같은 키 이름과 구조**로 씁니다. 예시는 형식만 보여 주는 것이니 내용은 새로 쓰세요.
- bible.episodes 에는 모든 회차의 줄거리를, episodes 에는 이번에 쓰는 회차의 컷 대본을 넣습니다.
- shot 은 "extreme close-up", "close-up", "medium close-up", "medium shot", "over-the-shoulder", "two shot", "wide shot", "insert" 중 하나.
- transition 은 "cut", "dissolve", "fade_black", "flash_white", "slide" 중 하나.
- 대사의 speaker 와 characters 에는 인물의 id 를 씁니다.
- JSON 앞뒤에 다른 설명은 쓰지 마세요.

[예시]
```json
{json.dumps(EXAMPLE, ensure_ascii=False, indent=1)}
```

※ 나중에 제가 "다음 화" 를 요청하면, 같은 인물·설정으로 {{"episodes": [ ...그 회차... ]}} 형식의 JSON 만 답해 주세요."""


# ── 2) 답변 읽기 ─────────────────────────────────────────
class ImportError_(ValueError):
    pass


def extract_json(text: str) -> dict:
    """답변에서 JSON 부분만 찾아 읽습니다. 코드블록 표시, 앞뒤 설명, 끝 쉼표 등은 알아서 정리합니다."""
    text = text.strip().lstrip("﻿")
    blocks = re.findall(r"```(?:json)?\s*(.*?)```", text, re.S)
    candidates = blocks + [text]
    last_err = None
    for cand in candidates:
        start, end = cand.find("{"), cand.rfind("}")
        if start < 0 or end <= start:
            continue
        body = cand[start:end + 1]
        for attempt in (body, re.sub(r",\s*([}\]])", r"\1", body)):
            try:
                data = json.loads(attempt)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError as e:
                last_err = e
    if "{" in text and text.count("{") > text.count("}"):
        raise ImportError_("답변이 중간에 끊긴 것 같아요(괄호가 덜 닫힘). 대화창에 '이어서 써 줘' 라고 하지 말고, "
                           "'회차 수를 줄여서 다시 써 줘' 라고 요청한 뒤 새 답변 전체를 복사해 주세요.")
    hint = f" ({last_err.msg}, {last_err.lineno}번째 줄)" if last_err else ""
    raise ImportError_("복사한 내용에서 대본(JSON)을 찾지 못했어요" + hint +
                       ". 대화창 답변의 코드블록 오른쪽 위 '복사' 버튼으로 복사했는지 확인해 주세요.")


def _slug(name: str, i: int) -> str:
    s = re.sub(r"[^a-z0-9]", "", name.lower())
    return s or f"char{i}"


def normalize(data: dict, cfg: dict) -> dict:
    """빠진 항목은 기본값으로 채우고, 숫자·목록 형식을 맞춥니다."""
    data = copy.deepcopy(data)
    eps = data.get("episodes") or ([data["episode"]] if data.get("episode") else [])
    out = {"episodes": []}
    if data.get("bible"):
        b = data["bible"]
        chars = []
        for i, c in enumerate(b.get("characters") or [], 1):
            cid = str(c.get("id") or _slug(str(c.get("name", "")), i)).strip()
            chars.append({
                "id": cid, "name": str(c.get("name") or cid), "role": str(c.get("role", "")),
                "age": int(re.sub(r"\D", "", str(c.get("age", ""))) or 0),
                "personality": str(c.get("personality", "")), "look_ko": str(c.get("look_ko", "")),
                "look_en": str(c.get("look_en") or c.get("look_ko") or ""), "voice": str(c.get("voice", "")),
            })
        if not chars:
            raise ImportError_("등장인물(characters)이 비어 있어요. 대화창에 다시 써 달라고 요청해 주세요.")
        outlines = []
        for i, o in enumerate(b.get("episodes") or [], 1):
            outlines.append({"no": int(o.get("no") or i), "title": str(o.get("title", f"{i}화")),
                             "hook": str(o.get("hook", "")), "summary": str(o.get("summary", "")),
                             "cliffhanger": str(o.get("cliffhanger", ""))})
        out["bible"] = {"title": str(b.get("title") or "제목 없음"), "logline": str(b.get("logline", "")),
                        "tone": str(b.get("tone", "")), "characters": chars, "episodes": outlines}
    for i, e in enumerate(eps, 1):
        cuts = []
        for j, c in enumerate(e.get("cuts") or [], 1):
            dialogue = []
            for d in c.get("dialogue") or []:
                if isinstance(d, dict) and str(d.get("line", "")).strip():
                    dialogue.append({"speaker": str(d.get("speaker", "")), "line": str(d["line"]).strip()})
            secs = int(re.sub(r"[^\d]", "", str(c.get("seconds", ""))) or cfg["cut_max"])
            cuts.append({
                "no": j, "seconds": secs, "location": str(c.get("location", "")),
                "time_of_day": str(c.get("time_of_day", "")),
                "characters": [str(x) for x in (c.get("characters") or [])],
                "shot": str(c.get("shot") or "medium shot"), "camera_move": str(c.get("camera_move") or "static"),
                "action_ko": str(c.get("action_ko", "")), "dialogue": dialogue,
                "emotion": str(c.get("emotion", "")), "sound": str(c.get("sound", "")),
                "video_prompt_en": str(c.get("video_prompt_en") or c.get("action_ko") or ""),
                "image_prompt_en": str(c.get("image_prompt_en") or c.get("video_prompt_en") or ""),
                "subtitle": str(c.get("subtitle") or (dialogue[0]["line"] if dialogue else "")),
                "transition": str(c.get("transition") or "cut"),
            })
        if not cuts:
            raise ImportError_(f"{i}번째 회차에 컷(cuts)이 없어요. 대화창에 다시 써 달라고 요청해 주세요.")
        ep = {"no": int(e.get("no") or i), "title": str(e.get("title") or f"{i}화"), "cuts": cuts}
        if e.get("thumbnail_text"):
            ep["thumbnail_text"] = str(e["thumbnail_text"]).replace("\\n", "\n")
            ep["thumbnail_cut"] = int(e.get("thumbnail_cut") or 1)
        up = e.get("upload")
        if isinstance(up, dict) and up.get("titles"):
            ep["upload"] = {"titles": [str(t) for t in up["titles"]], "description": str(up.get("description", "")),
                            "hashtags": [str(t) for t in up.get("hashtags") or []]}
        out["episodes"].append(ep)
    if not out["episodes"]:
        raise ImportError_("회차 대본(episodes)이 없어요. 대화창 답변 전체를 복사했는지 확인해 주세요.")
    return out


def merge_episodes(series: dict, new_eps: list[dict]) -> list[int]:
    """'다음 화' 답변을 기존 시리즈에 붙입니다. 같은 번호가 있으면 새 것으로 바꿉니다. 반환: 추가된 회차 번호"""
    have = {e["no"]: k for k, e in enumerate(series["episodes"])}
    added = []
    for e in new_eps:
        if e["no"] in have:
            series["episodes"][have[e["no"]]] = e
        else:
            series["episodes"].append(e)
        added.append(e["no"])
        if not any(o["no"] == e["no"] for o in series["bible"]["episodes"]):
            series["bible"]["episodes"].append({"no": e["no"], "title": e["title"], "hook": "", "summary": "",
                                                "cliffhanger": ""})
    series["episodes"].sort(key=lambda e: e["no"])
    series["bible"]["episodes"].sort(key=lambda o: o["no"])
    return added


# ── 클립보드 (윈도우) ─────────────────────────────────────
def read_clipboard() -> str:
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        try:
            return root.clipboard_get()
        finally:
            root.destroy()
    except Exception as e:
        raise ImportError_("클립보드를 읽지 못했어요. 답변을 메모장에 붙여넣어 저장한 뒤 "
                           "'python main.py import --file 파일이름.txt' 로 실행해 주세요.") from e


def write_clipboard(text: str) -> bool:
    import subprocess
    import sys
    if sys.platform != "win32":
        return False
    try:
        subprocess.run(["clip"], input=text.encode("utf-16"), check=True)   # utf-16(BOM 포함) = 한글 안 깨짐
        return True
    except Exception:
        return False
