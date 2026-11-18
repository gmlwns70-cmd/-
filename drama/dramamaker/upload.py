"""업로드용 제목·설명·해시태그를 플랫폼별(유튜브 쇼츠 / 틱톡 / 인스타 릴스)로 정리합니다.

Claude가 대본과 함께 만든 ep["upload"] 를 쓰고, 없으면(예전 대본) 대본 내용으로 기본 문구를 만듭니다.
"""
from __future__ import annotations

import re
from pathlib import Path

BASE_TAGS = ["숏드라마", "웹드라마"]
YT_TITLE_MAX = 100
YT_TAG_MAX = 15        # 유튜브는 해시태그가 너무 많으면(60개 초과) 전부 무시합니다. 넉넉히 15개로 제한
IG_TAG_MAX = 5         # 인스타그램은 3~5개를 권장
TT_TAG_MAX = 6
AI_NOTICE = ("⚠ 올리기 전에 꼭: 이 영상은 AI로 만든 사실적인 영상이에요.\n"
             "  - 유튜브: 업로드 화면 '변경되거나 합성된 콘텐츠' 항목에서 '예'를 고르세요.\n"
             "  - 틱톡: 게시 화면 '더 보기 → AI 생성 콘텐츠' 표시를 켜세요.\n"
             "  - 인스타그램: 'AI 정보' 라벨을 켜세요.")


def clean_tag(t: str) -> str:
    return re.sub(r"[^\w가-힣]", "", t.replace("#", "").replace(" ", ""))


def merge_tags(*groups, limit: int) -> list[str]:
    out = []
    for g in groups:
        for t in g:
            t = clean_tag(t)
            if t and t.lower() not in {x.lower() for x in out}:
                out.append(t)
    return out[:limit]


def fallback(series: dict, ep: dict) -> dict:
    """Claude가 만든 업로드 문구가 없을 때 대본 내용으로 기본 문구를 만듭니다."""
    bible = series["bible"]
    outline = next((o for o in bible["episodes"] if o["no"] == ep["no"]), {})
    hook = (ep.get("thumbnail_text") or "").replace("\n", " ").strip()
    titles = [t for t in (
        f"{hook} | {bible['title']} EP.{ep['no']:02d}" if hook else "",
        f"{ep['title']} | {bible['title']} EP.{ep['no']:02d}",
        f"[{bible['title']}] {ep['no']}화 - {ep['title']}",
    ) if t]
    genre = series.get("config", {}).get("genre", "로맨스")
    return {
        "titles": titles,
        "description": f"{outline.get('summary', bible['logline'])}\n\n{bible['logline']}",
        "hashtags": [genre, f"{genre}드라마", "AI드라마", bible["title"]],
    }


def build(series: dict, ep: dict) -> dict:
    up = ep.get("upload") or fallback(series, ep)
    bible = series["bible"]
    series_tag = clean_tag(bible["title"])
    n, total = ep["no"], len(series["episodes"])
    titles = [t.strip()[:YT_TITLE_MAX] for t in up["titles"] if t.strip()] or fallback(series, ep)["titles"]
    desc = up["description"].strip()
    nxt = "👉 다음 화도 이어서 올라와요. 구독하고 기다려 주세요!" if n < total else "💕 마지막 화예요. 끝까지 봐 주셔서 고마워요!"
    yt_tags = merge_tags(["Shorts", series_tag], up["hashtags"], BASE_TAGS, limit=YT_TAG_MAX)
    tt_tags = merge_tags([series_tag], BASE_TAGS, up["hashtags"], limit=TT_TAG_MAX)
    ig_tags = merge_tags([series_tag], BASE_TAGS, up["hashtags"], limit=IG_TAG_MAX)
    tag = lambda tags: " ".join(f"#{t}" for t in tags)  # noqa: E731
    first_line = desc.split("\n")[0]
    return {
        "titles": titles,
        "youtube": {"title": titles[0],
                    "description": f"{desc}\n\n📺 {bible['title']} EP.{n:02d} / 전 {total}화\n{nxt}\n\n{tag(yt_tags)}"},
        "tiktok": f"{titles[0]}\n{first_line}\n{tag(tt_tags)}",
        "instagram": f"{titles[0]}\n\n{desc}\n\n{nxt}\n.\n{tag(ig_tags)}",
    }


def write(path: Path, series: dict, ep: dict) -> None:
    b = build(series, ep)
    bar = "=" * 60
    lines = [f"EP{ep['no']:02d}. {ep['title']} — 업로드 문구", "복사해서 붙여넣으세요. 마음에 안 들면 이 파일을 직접 고쳐도 돼요.", "",
             AI_NOTICE, "", bar, "[제목 후보] 하나를 고르세요", bar]
    lines += [f"{i}. {t}  ({len(t)}자)" for i, t in enumerate(b["titles"], 1)]
    lines += ["", bar, "[유튜브 쇼츠] 제목", bar, b["youtube"]["title"], "",
              bar, "[유튜브 쇼츠] 설명", bar, b["youtube"]["description"], "",
              bar, "[틱톡] 캡션", bar, b["tiktok"], "",
              bar, "[인스타그램 릴스] 캡션", bar, b["instagram"], ""]
    path.write_text("\n".join(lines), encoding="utf-8")
