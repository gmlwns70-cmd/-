"""수치·통계 검증 도구.

원칙: 웹 검색으로 실제로 확인된 출처(URL)에 같은 숫자가 있을 때만 카드에 숫자를 남깁니다.
출처를 못 찾은 숫자는 지우고, 그 카드를 "검증 필요"로 표시합니다.
"""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import urlsplit

NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
NUM_WORDS = ["절반", "퍼센트", "프로", "과반", "대다수", "열에 아홉", "열 명 중"]


def numbers_in(text: str) -> list[str]:
    return [n.replace(",", "") for n in NUM_RE.findall(text)]


def has_figure(text: str) -> bool:
    return bool(NUM_RE.search(text)) or any(w in text for w in NUM_WORDS)


def card_text(card: dict) -> str:
    return " ".join(l.get("text", "") for l in card.get("lines", []))


def norm_url(url: str) -> str:
    try:
        p = urlsplit(url.strip())
        return f"{p.netloc.lower().removeprefix('www.')}{p.path.rstrip('/')}"
    except Exception:
        return url.strip().lower()


def verify_cards(script: dict, facts: list[dict]) -> list[dict]:
    """각 카드의 숫자가 검증된 출처와 맞는지 확인합니다. 문제 카드 목록을 돌려줍니다."""
    by_url = {norm_url(f["url"]): f for f in facts if f.get("url")}
    problems = []
    for card in script["cards"]:
        text = card_text(card)
        if not has_figure(text):
            continue
        src = (card.get("source") or {}).get("url", "")
        fact = by_url.get(norm_url(src)) if src else None
        if not fact:
            problems.append({"no": card["no"], "reason": "출처가 검증된 목록에 없음"})
            continue
        hay = re.sub(r",", "", " ".join(str(fact.get(k, "")) for k in ("claim", "figure", "date", "title", "publisher")))
        missing = [n for n in numbers_in(text) if n not in hay]
        if missing:
            problems.append({"no": card["no"], "reason": f"출처에 없는 숫자: {', '.join(missing)}"})
    return problems


def strip_unverified(script: dict, problem_nos: set[int]) -> None:
    """마지막 안전장치: 고쳐지지 않은 카드는 숫자가 든 줄을 빼고 '검증 필요'로 표시합니다."""
    for card in script["cards"]:
        if card["no"] not in problem_nos:
            continue
        kept = [l for l in card["lines"] if not has_figure(l.get("text", ""))]
        if not any(l.get("text", "").strip() for l in kept):
            kept = [{"text": "이 부분은", "highlight": False},
                    {"text": "확인이 더 필요해요", "highlight": True}]
        card["lines"] = kept
        card["source"] = {"name": "", "url": ""}
        card["verify_needed"] = True


def write_sources_md(path, script: dict, facts: list[dict]) -> None:
    used = {norm_url((c.get("source") or {}).get("url", "")): c["no"] for c in script["cards"]
            if (c.get("source") or {}).get("url")}
    out = [f"# 출처 목록 — {script.get('topic', '')}", "",
           f"- 작성일: {date.today().isoformat()}",
           "- 아래 URL은 원고 생성 중 웹 검색으로 실제 확인된 페이지입니다.",
           "- 올리기 전에 링크를 한 번씩 열어 숫자가 맞는지 꼭 직접 확인해 주세요.", ""]
    out += ["## 카드에 사용한 출처", ""]
    n = 0
    for f in facts:
        no = used.get(norm_url(f["url"]))
        if no is None:
            continue
        n += 1
        out.append(f"{n}. **{no}번 카드** — {f.get('publisher', '')} 「{f.get('title', '')}」 ({f.get('date', '날짜 미상')})")
        out.append(f"   - 내용: {f.get('claim', '')}")
        out.append(f"   - URL: {f['url']}")
    if n == 0:
        out.append("- (수치를 쓴 카드가 없습니다)")
    rest = [f for f in facts if norm_url(f["url"]) not in used]
    if rest:
        out += ["", "## 조사했지만 카드에 쓰지 않은 자료", ""]
        for f in rest:
            out.append(f"- {f.get('publisher', '')} 「{f.get('title', '')}」 — {f.get('claim', '')}  ")
            out.append(f"  {f['url']}")
    flagged = [c["no"] for c in script["cards"] if c.get("verify_needed")]
    if flagged:
        out += ["", "## ⚠ 검증 필요", "",
                f"- {', '.join(map(str, flagged))}번 카드: 출처를 찾지 못해 숫자를 빼고 일반 문장으로 바꿨습니다."]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
