"""6단계: 검수 리포트 (맞춤법 의심 / 출처 없는 수치 / 줄 길이 / 글자·인물 겹침)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import factcheck

# (틀리기 쉬운 표현, 바른 표현) — 자주 나오는 것 위주. 확실하지 않으면 '의심'으로만 알려 줍니다.
SPELLING = [
    (r"되요", "돼요"), (r"되서", "돼서"), (r"됬", "됐"), (r"안되요", "안 돼요"),
    (r"할께", "할게"), (r"줄께", "줄게"), (r"갈께", "갈게"), (r"몇일", "며칠"),
    (r"왠만", "웬만"), (r"어떻해", "어떡해"), (r"금새", "금세"), (r"오랫만", "오랜만"),
    (r"역활", "역할"), (r"희안", "희한"), (r"일일히", "일일이"), (r"깨끗히", "깨끗이"),
    (r"곰곰히", "곰곰이"), (r"바램", "바람"), (r"어의없", "어이없"), (r"내노라", "내로라"),
    (r"뵈요", "봬요"), (r"할려고", "하려고"), (r"설겆이", "설거지"), (r"구지", "굳이"),
    (r"않되", "안 되"), (r"않돼", "안 돼"), (r"되가", "돼 가"),
    (r"웬지", "왠지"),
]
FORMAL_END = re.compile(r"(습니다|합니다|입니다|이다|한다)[.!?]?$")


def _chars(text: str) -> int:
    return len(text.replace(" ", ""))


def run_check(out_dir: Path, cfg: dict) -> str:
    out_dir = Path(out_dir)
    script = json.loads((out_dir / "script.json").read_text(encoding="utf-8"))
    meta_path = out_dir / "render_meta.json"
    meta = {m["no"]: m for m in json.loads(meta_path.read_text(encoding="utf-8"))} if meta_path.exists() else {}
    st = cfg["style"]
    limit = int(st["line_max_chars"]) + int(st["line_tolerance"])

    spell, numbers, lengths, overlap, misc = [], [], [], [], []
    for card in script["cards"]:
        no = card["no"]
        texts = [l.get("text", "") for l in card.get("lines", [])]
        for t in texts:
            for wrong, right in SPELLING:
                if re.search(wrong, t):
                    spell.append(f"{no}번 「{t}」 → '{re.search(wrong, t).group(0)}' 대신 '{right}' 아닌지 확인")
            if FORMAL_END.search(t.strip()):
                spell.append(f"{no}번 「{t}」 → 해요체가 아닌 것 같아요")
            if "  " in t:
                spell.append(f"{no}번 「{t}」 → 띄어쓰기가 두 번 들어갔어요")
            if t.strip() and _chars(t) > limit:
                lengths.append(f"{no}번 「{t}」 {_chars(t)}자 (권장 {st['line_max_chars']}자)")
        joined = " ".join(texts)
        src = card.get("source") or {}
        if factcheck.has_figure(joined) and not src.get("url"):
            nums = factcheck.numbers_in(joined) or ["수치 표현"]
            numbers.append(f"{no}번 카드: {', '.join(nums)} — 출처 URL 없음")
        if src.get("url") and "따르면" not in joined:
            numbers.append(f"{no}번 카드: 출처는 있지만 본문에 'OO에 따르면' 표기가 없어요")
        if card.get("verify_needed"):
            numbers.append(f"{no}번 카드: '검증 필요' 표시가 붙어 있어요 (출처를 찾으면 원고를 고쳐 주세요)")

        m = meta.get(no)
        if m:
            for w in m.get("warnings", []):
                lengths.append(f"{no}번 카드: {w}")
            tb, fb = m.get("text_box"), m.get("figure_box")
            if tb and fb:
                ix = min(tb[2], fb[2]) - max(tb[0], fb[0])
                iy = min(tb[3], fb[3]) - max(tb[1], fb[1])
                if ix > 0 and iy > 0:
                    overlap.append(f"{no}번 카드: 글자와 인물이 약 {iy}px 겹쳐 보여요 → 줄 수를 줄이거나 그림을 다시 만들어 보세요")

    cap = script.get("caption") or {}
    body_len = len(cap.get("body", ""))
    if cap and not 800 <= body_len <= 1500:
        misc.append(f"캡션 본문이 {body_len}자예요 (권장 800~1500자)")
    if cap and len(cap.get("hashtags", [])) != 15:
        misc.append(f"해시태그가 {len(cap.get('hashtags', []))}개예요 (권장 15개)")
    if not meta:
        misc.append("render_meta.json 이 없어 겹침 검사를 건너뛰었어요 → render 명령을 먼저 실행하세요")

    def section(title, items, ok):
        return [f"## {title}", *(f"- {i}" for i in items)] if items else [f"## {title}", f"- ✅ {ok}"]

    report = [f"# 검수 리포트 — {script.get('topic', '')}", ""]
    report += section("맞춤법 의심 표현", spell, "의심 표현 없음") + [""]
    report += section("출처 없는 수치", numbers, "문제 없음") + [""]
    report += section("한 줄 글자 수 초과", lengths, f"모든 줄이 {limit}자 이하") + [""]
    report += section("글자와 인물 겹침 (대략)", overlap, "겹침 없음") + [""]
    if misc:
        report += section("기타", misc, "") + [""]
    report.append("※ 맞춤법은 자주 틀리는 표현만 자동으로 찾아요. 올리기 전 한 번 더 읽어 주세요.")
    text = "\n".join(report)
    (out_dir / "check_report.md").write_text(text + "\n", encoding="utf-8")
    return text
